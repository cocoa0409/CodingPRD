"""Domain thresholds and constants from PRD §2.5, §2.6, §3.2, §3.5, §3.8."""

# Logical clock (PRD §2.5): server startup default before any set call.
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# First-day-letter computation (PRD §3.2): ten business days from start.
FIRST_DAY_LETTER_BUSINESS_DAYS = 10

# Repeat-finding risk scoring (PRD §3.5): integer basis points.
SEVERITY_BASE_BP = {
    "LOW": 2500,
    "MODERATE": 5000,
    "HIGH": 7500,
    "CRITICAL": 10000,
}
MAX_SCORE_BP = 100000
OVERDUE_SURCHARGE_BP_PER_DAY = 25
OVERDUE_SURCHARGE_CAP_BP = 5000
REPEAT_MULTIPLIER_NEUTRAL_BP = 10000

# Posture (PRD §3.8): overdue-item count reaching three qualifies as FROZEN.
FROZEN_ITEM_THRESHOLD = 3

# Agency policy bounds (PRD §3.1).
ESCALATION_THRESHOLD_DAYS_MIN = 1
ESCALATION_THRESHOLD_DAYS_MAX = 730
REPEAT_MULTIPLIER_MIN_BP = 10000
REPEAT_MULTIPLIER_MAX_BP = 40000

TEST_DEFAULTS = {
    "ESCALATION_THRESHOLD_DAYS": 30,
    "REPEAT_MULTIPLIER_BP": 20000,
    "EXAM_START": "2026-07-06T00:00:00Z",
    "EXAM_END": "2026-07-10T00:00:00Z",
    "ITEM_DUE": "2026-07-15T00:00:00Z",
    "ISSUE_DUE": "2026-09-01T00:00:00Z",
    "MILESTONE_DUE": "2026-08-10T00:00:00Z",
    "MEETING_DATE": "2026-07-07T10:00:00Z",
}
