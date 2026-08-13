"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Exception priority scoring (PRD §3.7)
SEVERITY_BASE = {"WARNING": 100, "CRITICAL": 300}
DEAD_LETTER_BASE = 300
SENSITIVITY_MULT = {"PUBLIC": 1, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3}
AGE_TIER1_DAYS = 7
AGE_TIER1_BONUS = 50
AGE_TIER2_DAYS = 30
AGE_TIER2_BONUS = 150
SCORE_CAP = 1000

# Integration retry budget (PRD §3.6)
MAX_RETRY = 3

# Logical clock default (PRD §2.5)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# Effective-date window (PRD §3.4)
EFFECTIVE_DATE_LOOKBACK_DAYS = 730
EFFECTIVE_DATE_LOOKAHEAD_DAYS = 365

# Waiver window (PRD §3.7)
WAIVER_MAX_DAYS = 90

# Hierarchy depth cap (PRD §3.2)
MAX_HIERARCHY_DEPTH = 10

# Governable field keys (PRD §3.1)
GOVERNABLE_FIELD_KEYS = (
    "assignment.position_id",
    "assignment.salary_cents",
    "assignment.pay_grade",
    "assignment.location_code",
    "position.parent_position_id",
    "position.title",
    "position.department",
)
