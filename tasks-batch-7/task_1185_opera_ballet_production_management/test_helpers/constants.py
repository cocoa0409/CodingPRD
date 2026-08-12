"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Weekly pay overtime tiers (PRD §3.4)
OT_TIER1_SPAN_HOURS = 10
OT1_MULT = 1.5
OT2_MULT = 2.0
NIGHT_PREMIUM_CENTS = 1500
NIGHT_WINDOW_START_HOUR = 23  # ends_at time-of-day in [23:00, 24:00) UTC

# Seat pricing (PRD §3.8)
SECTION_MULT = {
    "STALLS": 1.0,
    "BALCONY": 1.25,
    "BOX": 1.6,
    "GALLERY": 0.8,
}
GROUP_MIN = 10
GROUP_DISCOUNT = 0.9
DEMAND_TIER_LOW = 0.5    # ratio >= 0.5 -> 1.2
DEMAND_TIER_HIGH = 0.8   # ratio >= 0.8 -> 1.5
DEMAND_MULT_BASE = 1.0
DEMAND_MULT_MID = 1.2
DEMAND_MULT_HIGH = 1.5

# Rental fee schedule (PRD §3.9)
LARGE_RENTAL_THRESHOLD_CENTS = 5_000_000
LARGE_RENTAL_SURCHARGE_PCT = 8
MAX_NEGOTIATION_ROUNDS = 5

# Stage changeover buffers (PRD §2.8)
RESET_BUFFER_HOURS = 2          # same production
CHANGEOVER_BUFFER_HOURS = 6     # different production

# Contracts (PRD §3.4)
DEFAULT_REST_FLOOR_HOURS = 12

# Logical clock (PRD §2.5)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "BUILD_BUDGET_CENTS": 100_000_000,
    "HOURLY_RATE_CENTS": 8_000,
    "WEEKLY_HOURS_CAP": 30,
    "ROOM_HOURLY_RATE_CENTS": 5_000,
    "ROOM_CAPACITY": 40,
    "BASE_PRICE_CENTS": 10_000,
}
