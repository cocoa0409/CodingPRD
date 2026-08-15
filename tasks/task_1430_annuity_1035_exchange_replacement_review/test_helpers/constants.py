"""Domain thresholds and canonical fixture values (PRD §2.4, §3)."""

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Surrender schedule projection lag (PRD §3.4).
    "SETTLEMENT_LAG_DAYS": 45,
    # Tax-basis / partial exchange bounds (PRD §3.2, §3.4).
    "MIN_PARTIAL_CENTS": 100000,
    # Rider benefit-loss cap (PRD §3.4).
    "RIDER_LOSS_CAP_CENTS": 2000000,
    # Break-even projection horizon (PRD §3.4).
    "MAX_PROJECTION_YEARS": 30,
    # Free-look lengths (PRD §3.7).
    "FREE_LOOK_DAYS_STANDARD": 20,
    "FREE_LOOK_DAYS_SENIOR": 30,
    "SENIOR_AGE": 65,
    # Producer surveillance (PRD §3.8).
    "CHURN_FLAG_MIN_COMPLETED_12M": 2,
    "RESCISSION_FLAG_BPS": 5000,
    "ANTI_CHURN_WINDOW_DAYS": 365,
    "COOLING_OFF_DAYS_AFTER_RESCISSION": 30,
}

TEST_DEFAULTS = {
    "PRODUCER_LICENSE": "LIC-001",
    "PRODUCER_NAME": "Pat Producer",
    "PRODUCER_STATE": "CA",
    "SENIOR_DOB": "1960-01-01",   # 66 at the 2026-08-01 default clock
    "JUNIOR_DOB": "1990-06-15",   # 36 at the 2026-08-01 default clock
    "CLIENT_STATE": "CA",
    "CARRIER_NAME": "OldLine",
    "CONTRACT_NUMBER": "CN-A",
    "ISSUE_DATE": "2021-09-01",   # 4 completed years at default clock; 5 at +45d
    "ACCOUNT_VALUE_CENTS": 10000000,
    "TAX_BASIS_CENTS": 8000000,
    "RIDER_BENEFIT_BASE_CENTS": 12000000,
    "RIDER_ANNUAL_FEE_BPS": 95,
    "NEW_PRODUCT_CODE": "NP-7",
    "NEW_PRODUCT_SURRENDER_YEARS": 7,
    "NEW_PRODUCT_BONUS_BPS": 100,
    "NEW_PRODUCT_ANNUAL_FEE_BPS": 115,
    "ASSUMED_OLD_GROWTH_BPS": 500,
    "ASSUMED_NEW_GROWTH_BPS": 600,
    "REVIEWER_ID": "rev-1",
    "PRINCIPAL_ID": "prin-1",
}

# Canonical 7-year surrender schedule: 700/600/500/400/300/200/100 bps.
K_STD_SCHEDULE = [
    {"contract_year": year, "pct_bps": pct}
    for year, pct in enumerate([700, 600, 500, 400, 300, 200, 100], start=1)
]
