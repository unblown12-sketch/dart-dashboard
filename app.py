import streamlit as st
import requests
import zipfile
import xml.etree.ElementTree as ET
import io
import pandas as pd
import json
from datetime import datetime

# ── 페이지 설정 ──────────────────────────────────────────────
st.set_page_config(
    page_title="DART 재무데이터 추출기",
    page_icon="📊",
    layout="wide"
)

st.title("📊 DART 재무데이터 추출기")
st.caption("DART 공시 기반 재무제표 조회 · 연결/별도 비교 · AI 분석용 프롬프트 생성")

# ── API 키 ──────────────────────────────────────────────────
API_KEY = st.secrets.get("DART_API_KEY", "96c5815ac8566f88156b32ce95352d75f9044a17")

# ── 상수 ────────────────────────────────────────────────────
REPORT_CODES = {
    "사업보고서 (연간)": "11011",
    "반기보고서": "11012",
    "1분기보고서": "11013",
    "3분기보고서": "11014",
}
FS_MAP = {
    "BS": "재무상태표",
    "IS": "손익계산서",
    "CIS": "포괄손익계산서",
    "CF": "현금흐름표",
    "SCE": "자본변동표",
}

# ── 캐시: 기업코드 ZIP (무거우므로 1회만 다운) ───────────────
@st.cache_data(show_spinner="기업코드 파일 다운로드 중...", ttl=3600)
def load_corp_codes(api_key):
    url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={api_key}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        with zf.open("CORPCODE.xml") as f:
            tree = ET.parse(f)
            root = tree.getroot()
    corps = []
    for item in root.findall("list"):
        corps.append({
            "corp_code": item.findtext("corp_code", ""),
            "corp_name": item.findtext("corp_name", ""),
            "stock_code": item.findtext("stock_code", ""),
        })
    return pd.DataFrame(corps)

def search_corp(df, name):
    return df[df["corp_name"].str.contains(name, na=False)]

@st.cache_data(show_spinner="재무데이터 조회 중...", ttl=1800)
def fetch_fs(corp_code, year, report_code, fs_div, api_key):
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": year,
        "reprt_code": report_code,
        "fs_div": fs_div,
    }
    resp = requests.get(url, params=params, timeout=30)
    data = resp.json()
    if data.get("status") == "000" and data.get("list"):
        return pd.DataFrame(data["list"])
    return pd.DataFrame()

def fmt_amount(val):
    try:
        n = int(str(val).replace(",", ""))
        if n == 0: return "-"
        abs_n = abs(n)
        if abs_n >= 1e12: return f"{n/1e12:.1f}조"
        if abs_n >= 1e8:  return f"{round(n/1e8):,}억"
        if abs_n >= 1e4:  return f"{round(n/1e4):,}만"
        return f"{n:,}"
    except:
        return str(val)

def calc_change(curr, prev):
    try:
        c = int(str(curr).replace(",", ""))
        p = int(str(prev).replace(",", ""))
        if p == 0: return None
        return round((c - p) / abs(p) * 100, 1)
    except:
        return None

# ── 사이드바 입력 ────────────────────────────────────────────
with st.sidebar:
    st.header("🔍 조회 설정")
    company_input = st.text_input("기업명", value="삼성전자", placeholder="예: LG에너지솔루션")
    year_input = st.text_input("결산연도", value="2023", max_chars=4)
    report_label = st.selectbox("보고서 종류", list(REPORT_CODES.keys()))
    report_code = REPORT_CODES[report_label]
    run_btn = st.button("📥 재무데이터 추출", use_container_width=True, type="primary")

    st.divider()
    st.caption("💡 연결·별도 모두 자동 추출됩니다")
    st.caption("💡 추출 후 AI 분석용 프롬프트를 복사해 Claude에 붙여넣으세요")

# ── 메인 ────────────────────────────────────────────────────
if run_btn:
    if not company_input or not year_input:
        st.error("기업명과 연도를 입력해 주세요.")
        st.stop()

    # 기업코드 로드 (캐시됨)
    with st.spinner("기업코드 검색 중..."):
        corp_df = load_corp_codes(API_KEY)
        results = search_corp(corp_df, company_input)

    if results.empty:
        st.error(f'"{company_input}" 검색 결과 없음. 기업명을 확인해 주세요.')
        st.stop()

    # 기업 선택 (여러 개면 선택)
    if len(results) > 1:
        st.info(f"'{company_input}' 검색 결과 {len(results)}건 — 아래에서 선택해 주세요.")
        selected_name = st.selectbox(
            "기업 선택",
            results["corp_name"].tolist(),
            key="corp_select"
        )
        selected = results[results["corp_name"] == selected_name].iloc[0]
    else:
        selected = results.iloc[0]

    corp_code = selected["corp_code"]
    corp_name = selected["corp_name"]

    st.session_state["corp_name"] = corp_name
    st.session_state["year"] = year_input
    st.session_state["report_label"] = report_label

    # 연결 · 별도 조회
    with st.spinner(f"{corp_name} 재무데이터 불러오는 중..."):
        df_cfs = fetch_fs(corp_code, year_input, report_code, "CFS", API_KEY)
        df_ofs = fetch_fs(corp_code, year_input, report_code, "OFS", API_KEY)

    st.session_state["df_cfs"] = df_cfs
    st.session_state["df_ofs"] = df_ofs

    if df_cfs.empty and df_ofs.empty:
        st.error("데이터 없음. 연도 또는 보고서 종류를 확인해 주세요.")
        st.stop()

    has_cfs = not df_cfs.empty
    has_ofs = not df_ofs.empty
    status_parts = []
    if has_cfs: status_parts.append("연결 ✓")
    if has_ofs: status_parts.append("별도 ✓")
    st.success(f"✅ {corp_name} {year_input}년 {report_label} — {' / '.join(status_parts)}")

# ── 결과 표시 ────────────────────────────────────────────────
if "df_cfs" in st.session_state or "df_ofs" in st.session_state:
    corp_name = st.session_state.get("corp_name", "")
    year = st.session_state.get("year", "")
    report_label_s = st.session_state.get("report_label", "")
    df_cfs = st.session_state.get("df_cfs", pd.DataFrame())
    df_ofs = st.session_state.get("df_ofs", pd.DataFrame())

    st.subheader(f"{corp_name} {year}년 {report_label_s}")

    # 연결/별도 탭
    tab_labels = []
    tab_dfs = []
    if not df_cfs.empty:
        tab_labels.append("📘 연결재무제표")
        tab_dfs.append(df_cfs)
    if not df_ofs.empty:
        tab_labels.append("📗 별도재무제표")
        tab_dfs.append(df_ofs)

    tabs = st.tabs(tab_labels)

    for tab, df in zip(tabs, tab_dfs):
        with tab:
            # 핵심지표 카드
            key_accounts = ["자산총계", "부채총계", "자본총계", "매출액", "영업이익", "당기순이익"]
            metrics = {}
            for _, row in df.iterrows():
                if row.get("account_nm") in key_accounts:
                    metrics[row["account_nm"]] = row.get("thstrm_amount", "0")

            cols = st.columns(6)
            for i, acc in enumerate(key_accounts):
                val = fmt_amount(metrics.get(acc, 0))
                cols[i].metric(acc, val)

            st.divider()

            # 재무제표별 탭
            fs_tabs_labels = []
            fs_tabs_data = {}
            for code, name in FS_MAP.items():
                subset = df[df["sj_div"] == code] if "sj_div" in df.columns else pd.DataFrame()
                if not subset.empty:
                    fs_tabs_labels.append(name)
                    fs_tabs_data[name] = subset

            if fs_tabs_labels:
                fs_tabs = st.tabs(fs_tabs_labels)
                for fs_tab, fs_name in zip(fs_tabs, fs_tabs_labels):
                    with fs_tab:
                        subset = fs_tabs_data[fs_name].copy()
                        display_rows = []
                        for _, row in subset.iterrows():
                            curr = row.get("thstrm_amount", "")
                            prev = row.get("frmtrm_amount", "")
                            chg = calc_change(curr, prev)
                            chg_str = f"+{chg}%" if chg and chg > 0 else (f"{chg}%" if chg is not None else "-")
                            display_rows.append({
                                "계정과목": row.get("account_nm", ""),
                                "당기": fmt_amount(curr),
                                "전기": fmt_amount(prev),
                                "증감률": chg_str,
                            })
                        st.dataframe(
                            pd.DataFrame(display_rows),
                            use_container_width=True,
                            hide_index=True,
                            height=400
                        )

                        # 엑셀 다운로드
                        raw_cols = ["account_nm", "thstrm_amount", "frmtrm_amount", "sj_div", "account_id"]
                        avail = [c for c in raw_cols if c in subset.columns]
                        excel_buf = io.BytesIO()
                        subset[avail].to_excel(excel_buf, index=False)
                        st.download_button(
                            f"⬇️ {fs_name} 엑셀 다운로드",
                            data=excel_buf.getvalue(),
                            file_name=f"{corp_name}_{year}_{fs_name}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_{fs_name}_{tab_labels.index(list(zip(tabs, tab_dfs))[list(tab_dfs).index(df)][1] if False else '')}"
                        )

    # AI 분석용 프롬프트
    st.divider()
    st.subheader("🤖 Claude 분석용 프롬프트")

    main_df = df_cfs if not df_cfs.empty else df_ofs
    fs_label = "연결재무제표" if not df_cfs.empty else "별도재무제표"

    prompt_lines = [
        f"# {corp_name} {year}년 재무데이터 (DART 공시 / {report_label_s} / {fs_label})\n",
        "아래 재무데이터를 바탕으로 기업 신용분석을 해주세요.",
        "분석 항목: 수익성 / 안정성 / 성장성 / 현금흐름 / 종합의견\n",
    ]
    grouped = main_df.groupby("sj_div") if "sj_div" in main_df.columns else {}
    for code, name in FS_MAP.items():
        if "sj_div" in main_df.columns:
            subset = main_df[main_df["sj_div"] == code]
            if not subset.empty:
                prompt_lines.append(f"\n## {name}")
                for _, row in subset.iterrows():
                    prompt_lines.append(
                        f"- {row.get('account_nm','')}: 당기 {fmt_amount(row.get('thstrm_amount',''))} / 전기 {fmt_amount(row.get('frmtrm_amount',''))}"
                    )

    prompt_text = "\n".join(prompt_lines)
    st.text_area("아래 전체 복사 → Claude에 붙여넣기", prompt_text, height=200)
    st.download_button(
        "⬇️ 프롬프트 텍스트 파일 다운로드",
        data=prompt_text,
        file_name=f"{corp_name}_{year}_AI분석용.txt",
        mime="text/plain"
    )
