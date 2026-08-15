"""Domain thresholds and shared defaults from the PRD's calculation rules."""

# Quality grading ladder (PRD §3.5)
SHRINKAGE_REJECT_PCT = 8.0    # shrinkage input >= 8.0 grades REJECTED
SHRINKAGE_SECOND_PCT = 5.0    # shrinkage input >= 5.0 (and < 8.0) grades SECOND_QUALITY
HAND_MIN = 3                  # hand_score under 3 forces SECOND_QUALITY

# Yarn count deviation tolerance (PRD §3.2)
COUNT_TOLERANCE_PCT = 3.0

# Vat scheduling cooldown (PRD §2.9)
VAT_COOLDOWN_MINUTES = 30

# Greige yards-per-pound by English count band (PRD §3.2)
YARDS_PER_LB_BY_COUNT = {
    10: 8400,
    20: 16800,
    30: 25200,
}

# Customer order default over/under-ship allowance (PRD §3.7)
DEFAULT_YARDAGE_TOLERANCE_PCT = 2.0

# Common schedule anchors used across floor-scheduling tests
DEFAULT_WINDOW_START = "2026-08-14T08:00:00Z"
DEFAULT_WINDOW_END = "2026-08-14T12:00:00Z"
DEFAULT_SCHEDULED_AT = "2026-08-14T08:00:00Z"

# Standard shade band payload values (CIELAB centroid for NAVY-2B)
DEFAULT_CENTROID_L = 30.0
DEFAULT_CENTROID_A = 5.0
DEFAULT_CENTROID_B = -20.0
DEFAULT_DELTA_E_TOLERANCE = 1.5
