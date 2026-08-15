"""Domain thresholds and shared instants from the PRD."""

# Logical clock default (PRD §2.5): before any clock-setting call the logical
# clock reads exactly this instant.
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# Regulator defaults (PRD §3.1)
DEFAULT_ESCALATION_INTERVAL_DAYS = 10
DEFAULT_REMINDER_DAYS_BEFORE_DUE = 7

# Curriculum defaults (PRD §3.1)
DEFAULT_MAX_ATTEMPTS = 3

# Submission / score bounds (PRD §2.6)
SCORE_MIN = 0
SCORE_MAX = 100

# Extension bounds (PRD §3.5)
EXTEND_BY_DAYS_MIN = 1
EXTEND_BY_DAYS_MAX = 30

# Role-change temporal limits (PRD §3.3)
ROLE_CHANGE_RETROACTIVE_DAYS = 30
ROLE_CHANGE_REVERSE_WINDOW_DAYS = 14

# HARD-criticality escalation acceleration (PRD §3.5): threshold is half the
# escalation interval, rounded up to a whole day.
HARD_ACCELERATION_DIVISOR = 2

# Common instants used by scenarios
T0 = "2026-08-03T09:00:00Z"          # standard "now" for scenario setup (a Monday)
VERSION_EFFECTIVE_FROM = "2026-08-01T00:00:00Z"
HIRED_AT = "2026-08-03T09:00:00Z"

TEST_DEFAULTS = {
    "RECORDKEEPING_YEARS": 7,
    "PASSING_SCORE_PCT": 80,
    "VALIDITY_MONTHS": 12,
    "DUE_IN_DAYS": 30,
    "CAMPAIGN_YEAR": 2026,
    "CAMPAIGN_WINDOW_OPEN": "2026-08-01T00:00:00Z",
    "CAMPAIGN_WINDOW_CLOSE": "2026-09-01T00:00:00Z",
}
