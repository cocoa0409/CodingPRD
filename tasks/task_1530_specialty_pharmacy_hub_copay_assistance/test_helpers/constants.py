"""Domain thresholds and defaults — numeric constants from the PRD."""

# Logical clock startup default (PRD section 2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Refill adherence gate (PRD section 3.7): exactly 80.0 passes.
REFILL_MIN_PDC_PCT = 80.0

# Prior-authorization appeal hard cap (PRD section 3.3, MAX_APPEAL_ROUNDS).
MAX_APPEAL_ROUNDS = 2

# Adverse-event reporting window in hours (PRD section 3.8).
AE_REPORT_WINDOW_HOURS = 24

# Pagination envelope bounds (PRD section 2.3).
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

TEST_DEFAULTS = {
    "DIAGNOSIS_CODE": "C50",
    "MIN_DAYS_BETWEEN_FILLS": 20,
    "CARD_PER_FILL_CAP_CENTS": 15_000,
    "CARD_ANNUAL_CAP_CENTS": 100_000,
    "DEFAULT_DAYS_SUPPLY": 30,
    "TRANSIT_HOURS": 24,
    "PATIENT_COST_SHARE_CENTS": 20_000,
    "OOP_MAX_CENTS": 500_000,
    "POOL_TOTAL_FUNDING_CENTS": 5_000_000,
    "POOL_GRANT_AMOUNT_CENTS": 200_000,
    "POOL_COVERAGE_PCT": 80,
    "POOL_START_DATE": "2026-01-01",
    "POOL_END_DATE": "2026-12-31",
}
