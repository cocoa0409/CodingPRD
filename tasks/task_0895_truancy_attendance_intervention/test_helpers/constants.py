"""Domain thresholds and defaults from the PRD calculations and policy constants."""

# Default school policy constants (PRD §3.1).
SCHOOL_DEFAULTS = {
    "TIER1_UNEXCUSED_THRESHOLD": 3,
    "TIER2_UNEXCUSED_THRESHOLD": 6,
    "TIER3_UNEXCUSED_THRESHOLD": 10,
    "COURT_UNEXCUSED_THRESHOLD": 15,
    "REQUIRED_INSTRUCTIONAL_DAYS": 180,
    "CHRONIC_ABSENCE_PCT_THRESHOLD": 10.0,
}

# Low-threshold profile used by escalation/cascade fixtures so a handful of
# UNEXCUSED records is enough to walk NONE -> TIER_1 -> TIER_2 -> TIER_3 -> COURT.
LOW_THRESHOLDS = {
    "tier1_unexcused_threshold": 1,
    "tier2_unexcused_threshold": 2,
    "tier3_unexcused_threshold": 3,
    "court_unexcused_threshold": 4,
}

# Staff default caseload cap (PRD §3.1).
DEFAULT_MAX_CASELOAD = 25

# Compliance scoring / lifecycle thresholds (PRD §3.6).
FULFILL_THRESHOLD = 80.0

# Buffered courtroom overlap window (PRD §3.8).
HEARING_BUFFER_MINUTES = 30

# Elementary band ceiling (grade_level <= 5); above it is SECONDARY (PRD §3.1).
ELEMENTARY_MAX_GRADE = 5
