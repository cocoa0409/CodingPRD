"""Domain thresholds and shared constants (PRD §2.5, §3.3-§3.9)."""

# Logical clock startup default (PRD §2.5)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Filing deadlines (PRD §3.4)
    "FORM4_BUSINESS_DAYS": 2,
    "FORM3_CALENDAR_DAYS": 10,
    "FORM5_CALENDAR_DAYS_AFTER_FY_END": 45,
    # 10b5-1 cooling-off (PRD §3.6)
    "COOLING_OFF_BASE_DAYS": 90,
    "COOLING_OFF_CAP_DAYS": 120,
    "EARNINGS_LAG_BUSINESS_DAYS": 2,
    # Beneficial ownership thresholds (PRD §3.7)
    "FILING_THRESHOLD_PCT": 5.00,
    "AMENDMENT_DELTA_PCT": 1.00,
    # Delinquency (PRD §3.4)
    "DELINQUENT_LATE_THRESHOLD": 2,
    # Short-swing window (PRD §3.9)
    "SHORT_SWING_WINDOW_MONTHS": 6,
}

TEST_DEFAULTS = {
    "ISSUER_NAME": "Acme Corp",
    "TICKER": "ACME",
    "CIK": "0000000001",
    "EDGAR_CCC": "CCC12345",
    "SHARES_OUTSTANDING": 1000000,
    "FISCAL_YEAR_END_MONTH": 12,
    "PERSON_NAME": "Dana Officer",
    "PERSON_CIK": "0001000001",
    "HOLDER_NAME": "Big Fund LP",
    # Opaque operator identifiers (PRD §2.1)
    "COMPLIANCE_OFFICER_ID": "co_1",
    "FILING_COORDINATOR_ID": "coord_1",
    "FILING_AGENT_ID": "agent_1",
    "EQUITY_PLAN_ADMIN_ID": "epa_1",
    "ACCESSION_NUMBER": "0000000001-26-000001",
}
