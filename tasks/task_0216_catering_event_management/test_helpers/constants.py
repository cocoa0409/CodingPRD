"""Domain thresholds — numeric constants from PRD calculations (§3.4–§3.10)."""

# Grand-total gratuity bands (PRD §3.4)
GRATUITY_BASE_BPS = 1800
GRATUITY_LARGE_BPS = 2200
GRATUITY_TIER_CENTS = 5_000_000

# Guarantee floor (PRD §3.4 effective headcount)
GUARANTEE_FLOOR_PCT = 90

# Deposit (PRD §3.5)
DEPOSIT_PCT = 25
DEPOSIT_RUSH_PCT = 50
RUSH_HOURS = 72
DEPOSIT_FLOOR_CENTS = 10_000

# Cancellation refund tiers (PRD §3.9)
FULL_REFUND_HOURS = 168
HALF_REFUND_HOURS = 72

# Change fee (PRD §3.10)
CHANGE_FREE_HOURS = 336
CHANGE_TIER_HOURS = 72
CHANGE_BASE_CENTS = 5_000
CHANGE_PER_HEAD_CENTS = 150
CHANGE_RUSH_MULT = 1.5

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Convenient defaults used across fixtures/tests.
TEST_DEFAULTS = {
    "PER_HEAD_CENTS": 5000,
    "MIN_HEADCOUNT": 1,
    "LEAD_TIME_HOURS": 24,
    "TAX_RATE_BPS": 875,
    "SERVICE_FEE_BPS": 2000,
    "MAX_OVERLAPPING_EVENTS": 5,
    "BOOKED_HEADCOUNT": 80,
    "VEHICLE_CAPACITY_LEGS": 3,
    "STAFF_POOL": 50,
}
