"""Domain thresholds — numeric constants from the PRD's calculations (§2.6, §3.5, §3.6, §3.7)."""

THRESHOLDS = {
    # Statutory interest on escheated remittance (§3.5).
    "ANNUAL_INTEREST_RATE": 0.02,
    "MAX_INTEREST_MULTIPLE": 0.5,
    # Recovery-fee cap (§3.6, §3.7).
    "STATE_MAX_FEE_PCT": 0.10,
    # Payout-waterfall administrative deduction (§3.7).
    "ADMIN_FLAT_FEE_CENTS": 500,
    "ADMIN_TIER_THRESHOLD_CENTS": 100000,
    "ADMIN_PCT": 0.005,
    # Due-diligence notice spacing buffer (§3.3).
    "DUE_DILIGENCE_NOTICE_BUFFER_DAYS": 30,
}

# Logical-clock startup default (§2.5).
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "AMOUNT_CENTS": 100000,
    "DORMANCY_PERIOD_YEARS": 3,
    "LAST_ACTIVITY_DATE": "2020-01-01T00:00:00Z",
    "ISSUE_DATE": "2020-01-01T00:00:00Z",
    "REPORT_YEAR": 2026,
}
