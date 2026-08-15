"""Domain thresholds — numeric constants from PRD calculations (§2.5, §3)."""

# Logical clock startup default (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_ISO_MILLIS = "2026-08-01T00:00:00.000Z"

# HVA plan-review trigger (PRD §3.1).
PLAN_REVIEW_TRIGGER_SCORE = 6

# Surge tier boundaries, evaluated by integer cross-multiplication (PRD §2.10, §3.4).
TIER_YELLOW_FLOOR_PCT = 85
TIER_ORANGE_FLOOR_PCT = 100
TIER_RED_FLOOR_PCT = 115

# Burn-rate window and surge multipliers (PRD §3.6).
BURN_WINDOW_HOURS = 168
BURN_WINDOW_DAYS = 7
SURGE_MULTIPLIER_BY_TIER = {
    "GREEN": 1.0,
    "YELLOW": 1.25,
    "ORANGE": 1.5,
    "RED": 2.0,
}

# Regulatory filing offsets in hours (PRD §3.9).
DUE_OFFSET_HOURS_BY_REPORT_TYPE = {
    "SITREP": 24,
    "RESOURCE_REQUEST": 24,
    "SURGE_CAPACITY": 72,
    "AAR_SUMMARY": 720,
}

# Buffered-overlap turnaround applied on both sides of a committed window (PRD §3.7).
ACS_COMMIT_BUFFER_HOURS = 4

# Default call-back response window (PRD §3.5).
DEFAULT_RESPONSE_WINDOW_HOURS = 2

# Convenience window covering the startup logical clock, used to make a
# committed site immediately activatable.
WINDOW_COVERING_DEFAULT_CLOCK = ("2026-07-31T00:00:00Z", "2026-08-05T00:00:00Z")
