"""Domain thresholds — numeric constants from the PRD's calculation narratives."""

# Residual benefit factor (PRD §3.9): minimum loss ratio and presumed-total ratio.
MIN_LOSS_RATIO = 0.20
PRESUMED_TOTAL_RATIO = 0.80

# COLA-adjusted gross (PRD §3.10): compounding caps benefit at 2x base.
MAX_COLA_MULTIPLIER = 2.0

# Net benefit waterfall floor (PRD §3.10): net benefit never goes negative.
OFFSET_FLOOR_CENTS = 0

# Elimination & proof-cadence (PRD §3.4 / §3.6).
DAYS_PER_MONTH = 30
PROOF_INTERVAL_MONTHS = 3

# Clock advance bounds (PRD §2.4).
CLOCK_ADVANCE_MIN = 1
CLOCK_ADVANCE_MAX = 100000

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Common test payload defaults.
TEST_DEFAULTS = {
    "MONTHLY_BENEFIT_CENTS": 500000,
    "PRE_DISABILITY_INCOME_CENTS": 1000000,
    "BENEFIT_PERIOD_MONTHS": 12,
    "ELIMINATION_PERIOD_DAYS": 90,
    "MAX_BENEFIT_MONTHS": 120,
}
