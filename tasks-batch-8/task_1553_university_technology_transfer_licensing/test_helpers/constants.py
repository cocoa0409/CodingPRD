"""Domain thresholds — numeric constants stated in the PRD."""

# Logical clock startup value (PRD: "before any administrative action, the
# logical clock reads exactly 2026-08-01T00:00:00Z").
CLOCK_START = "2026-08-01T00:00:00Z"

# Royalty acceptance pricing
TIER1_SALES_CAP_CENTS = 100_000_000

# Distribution waterfall percentages
ADMIN_FEE_PCT = 25
INVENTOR_PCT_FEDERAL = 40
INVENTOR_PCT_NONFEDERAL = 35
STARTUP_LINKED_REDUCTION_PCT = 5
SHARE_TOTAL_BP = 10_000

# Cost ledger write-off review threshold
WRITE_OFF_REVIEW_THRESHOLD_CENTS = 5_000_000

# Federal compliance due-date constants (days)
INITIAL_REPORT_DUE_DAYS = 180
ELECTION_DUE_DAYS = 730
BAR_DATE_DAYS = 365
BAR_BUFFER_DAYS = 30

# Startup equity variants
EQUITY_FIXED_BP = 500
AD_BASE_BP = 800
BASE_VALUATION_CENTS = 1_000_000_000
EQUITY_FLOOR_BP = 200
EQUITY_CAP_BP = 1500

# License execution fiscal floor
EXCLUSIVE_MIN_UPFRONT_CENTS = 500_000

# Default/cure window
CURE_PERIOD_DAYS = 60

TEST_DEFAULTS = {
    "DEPARTMENT_NAME": "EECS",
    "COLLEGE_NAME": "Engineering",
    "ROYALTY_RATE_BP": 500,
    "EFFECTIVE_DATE": "2026-01-01T00:00:00Z",
    "EXPIRATION_DATE": "2030-01-01T00:00:00Z",
    "COI_COVERAGE_START": "2026-01-01T00:00:00Z",
    "COI_COVERAGE_END": "2027-01-01T00:00:00Z",
    "REPORT_PERIOD_START": "2026-01-01T00:00:00Z",
    "REPORT_PERIOD_END": "2026-07-01T00:00:00Z",
}
