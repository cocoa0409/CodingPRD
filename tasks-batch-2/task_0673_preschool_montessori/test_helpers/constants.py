"""Domain thresholds — numeric constants from the PRD's tuition, ratio, and waitlist rules."""

# Tuition net calculation (PRD §3.6).
SIBLING_DISCOUNT_PCT = 0.10
FINANCIAL_AID_FLOOR_CENTS = 300_000

# Waitlist priority weights (PRD §3.3).
SIBLING_WEIGHT = 1000
STAFF_CHILD_WEIGHT = 1500
DAYS_WEIGHT = 1
TENURE_CAP_DAYS = 365

# Ratio / licensing compliance — students-per-staff caps by level (PRD §2.8).
LEVEL_RATIO = {
    "TODDLER": 6,
    "PRIMARY": 10,
    "ELEMENTARY": 12,
}

# Pagination bounds (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Default clock instant before any client sets it (PRD §2.6).
CLOCK_DEFAULT = "2026-04-01T00:00:00Z"

# Common test values reused across fixtures.
TEST_DEFAULTS = {
    "STD_BASE_ANNUAL_CENTS": 1_000_000,
    "STD_DEPOSIT_PCT": 0.10,
    "STD_INSTALLMENTS": 10,
    "STD_DEPOSIT_CENTS": 100_000,
    "PRIMARY_MIN_AGE": 36,
    "PRIMARY_MAX_AGE": 72,
}
