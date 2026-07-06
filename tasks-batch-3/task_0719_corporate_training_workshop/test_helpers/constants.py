"""Domain thresholds — numeric constants from PRD calculations and conventions."""

# NPS classification thresholds (PRD §3.7)
NPS = {
    "PROMOTER_MIN": 9,
    "DETRACTOR_MAX": 6,
}

# Server startup logical-clock default (PRD §2.4)
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# Pagination defaults (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Common per-seat money figures reused across fixtures (cents)
TEST_DEFAULTS = {
    "PER_SEAT_CENTS": 50000,
    "MATERIALS_KIT_CENTS": 2500,
    "TRAVEL_BASE_CENTS": 10000,
    "FLAT_FEE_CENTS": 200000,
}
