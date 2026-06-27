"""Domain thresholds — numeric constants from the PRD's calculations."""

# §3.4 / §3.6 order totals: point value used to convert redeem points to cents.
POINT_VALUE_CENTS = 5

# §3.5 loyalty accrual: GOLD multiplier doubles the rate.
GOLD_MULTIPLIER = 2

# §3.7 special-order deposit percentage.
DEPOSIT_PCT = 30

# §3.1 nursery policy defaults.
DEFAULT_LOYALTY_ACCRUAL_PER_DOLLAR = 1
DEFAULT_GOLD_TIER_THRESHOLD_POINTS = 1000
DEFAULT_SHRINK_WRITEOFF_ZONE_GRACE = 2

# §2.3 pagination.
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# §2.4 logical clock startup default.
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"
