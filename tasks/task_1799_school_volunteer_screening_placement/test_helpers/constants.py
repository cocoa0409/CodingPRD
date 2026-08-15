"""Domain thresholds and shared constants from the PRD's calculation rules."""

# Logical clock default at server startup (PRD: the clock reads exactly
# 2026-08-01T00:00:00Z before any set call).
CLOCK_DEFAULT_PREFIX = "2026-08-01T00:00:00"

# Clearance validity windows in whole days (PRD clearance validity window).
VALIDITY_DAYS = {
    "BASIC": 730,
    "ENHANCED": 365,
}

# Recognition ladder rungs in verified hours; boundaries are inclusive.
TIER_THRESHOLDS = {
    "BRONZE_MIN": 20.0,
    "SILVER_MIN": 50.0,
    "GOLD_MIN": 100.0,
}

# Recognition-points multipliers per activity category.
POINT_MULTIPLIERS = {
    "STANDARD": 1.0,
    "TUTORING": 1.5,
    "MENTORING": 2.0,
}

# A single hour entry may declare at most twelve hours.
HOURS_MAX_PER_ENTRY = 12.0

# Placement-linked check-ins open thirty minutes before the window start.
CHECKIN_EARLY_BUFFER_MINUTES = 30

# Badge sequence numbers are zero-padded to four digits.
BADGE_PAD_WIDTH = 4

# Default service window used by most scenarios (a future afternoon at the
# default logical clock).
DEFAULT_WINDOW_START = "2026-08-10T14:00:00Z"
DEFAULT_WINDOW_END = "2026-08-10T17:00:00Z"
DEFAULT_WORKED_DATE = "2026-08-10"

# Multi-day window used by accumulation scenarios.
WEEK_WINDOW_START = "2026-08-03T08:00:00Z"
WEEK_WINDOW_END = "2026-08-07T20:00:00Z"
