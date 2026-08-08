"""Domain thresholds — numeric constants from the PRD's pricing and window rules."""

# Threshold / multiplier constants named in the PRD narratives.
THRESHOLDS = {
    "OVERSIZE_THRESHOLD_CM": 150,   # §3.3 a bag is oversize when dimension_sum_cm >= 150
    "LATE_FEE_MULTIPLIER": 2,       # §3.6 late-fee multiplier of 2
    "PAYOUT_HOLD_DAYS": 2,          # §3.7 release hold of 2 days after pickup
    "CLAIM_WINDOW_DAYS": 3,         # §3.8 claim window of 3 days after pickup_at
}

# Default host commission and concurrency ceiling (§3.1).
DEFAULT_PLATFORM_FEE_BPS = 2000
DEFAULT_MAX_CONCURRENT_BOOKINGS = 5

# Common test pricing defaults (chosen so worked examples match the design index).
TEST_DEFAULTS = {
    "PER_BAG_DAY_RATE_CENTS": 500,
    "OVERSIZE_SURCHARGE_CENTS_PER_DAY": 300,
    "DAILY_BAG_CAPACITY": 10,
    "OVERSIZE_CAPACITY": 5,
    "PREMIUM_CENTS_PER_BAG_DAY": 200,
    "PREMIUM_COVERAGE_CENTS": 50000,
}

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"
