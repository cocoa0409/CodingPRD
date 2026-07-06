"""Domain thresholds - numeric constants from PRD calculations."""

# Loyalty tier thresholds (integer cents; at-least comparison).
LOYALTY = {
    "SILVER_CENTS": 50000,
    "GOLD_CENTS": 150000,
    "POINT_VALUE_CENTS": 1,
    "POINTS_DIVISOR_CENTS": 100,
}

# Framing quote constants.
FRAMING = {
    "BASE_CENTS": 2000,
    "SMALL_RATE_CENTS": 15,
    "MED_RATE_CENTS": 25,
    "LARGE_RATE_CENTS": 40,
    "SMALL_MAX_UNITED_IN": 40,
    "MED_MAX_UNITED_IN": 80,
}

# Special-order deposit.
SPECIAL_ORDER = {
    "DEPOSIT_PCT": 0.50,
}

# Product defaults.
DEFAULT_MIN_CUT_INCREMENT_YARDS = 0.25

# Server startup default clock instant.
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"
