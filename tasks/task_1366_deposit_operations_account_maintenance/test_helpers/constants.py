"""Domain thresholds — numeric constants named in the PRD.

Dormancy windows, fee schedule, garnishment lookback/answer period, the
state exemption floor, the accrual year basis, and the rate bound are all
pinned in PRD prose (sections 2.5, 2.6, 3.5, 3.8).
"""

THRESHOLDS = {
    # Dormancy evaluation windows (whole calendar days)
    "DORMANT_DAYS": 365,
    "ESCHEAT_DAYS": 1095,
    "ESCHEAT_CLOSE_DAYS": 1125,
    # Inactivity fee schedule
    "INACTIVITY_FEE_CENTS": 500,
    "FEE_PERIOD_DAYS": 30,
    # Garnishment / exempt-funds analysis
    "LOOKBACK_DAYS": 60,
    "ANSWER_PERIOD_DAYS": 20,
    "STATE_EXEMPT_FLOOR_CENTS": 100000,
    # Interest accrual
    "DAYS_IN_YEAR": 365,
    # Rate bounds (inclusive)
    "RATE_BPS_MIN": 0,
    "RATE_BPS_MAX": 2000,
}

# Logical clock default before any set call (PRD section 2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

TEST_DEFAULTS = {
    "OPENING_DEPOSIT_CENTS": 5000,
    "PRODUCT_CODE": "SAVINGS",
    "RATE_BPS": 0,
    "OWNERSHIP_TYPE": "INDIVIDUAL",
}
