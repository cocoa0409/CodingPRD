"""Domain thresholds and constants from the PRD (§2.5, §3.1, §3.5, §3.7, §3.9)."""

# Logical clock startup default (PRD §2.5).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Campaign tuning-knob defaults (PRD §3.1).
DEFAULT_AUTO_CONFIRM_THRESHOLD = 0.90
DEFAULT_REVIEW_FLOOR = 0.60
DEFAULT_MIN_SUBGROUP_SIZE = 5
DEFAULT_MAX_CASELOAD = 25
DEFAULT_NO_SHOW_LIMIT = 3
DEFAULT_MIN_RECOGNITION_SENIORS = 10

# Match-score component weights (PRD §3.5); exact tenths, sum to 1.00.
W_DOB = 0.40
W_NAME = 0.35
W_SCHOOL = 0.15
W_DISTRICT = 0.10

# Venue buffer between events of one school at publish (PRD §3.7).
VENUE_BUFFER_MINUTES = 30

# Checklist templates in item creation order (PRD §3.9).
TEMPLATE_DEPENDENT_STANDARD = [
    "STUDENT_ID",
    "STUDENT_TAX_RETURN",
    "PARENT_TAX_RETURN",
    "BANK_STATEMENT",
]
TEMPLATE_INDEPENDENT_STANDARD = [
    "STUDENT_ID",
    "STUDENT_TAX_RETURN",
    "DEPENDENCY_OVERRIDE_FORM",
]
WAIVABLE_DOC_TYPES = {"BANK_STATEMENT", "DEPENDENCY_OVERRIDE_FORM"}

# Canonical campaign deadlines used by most fixtures (PRD §3.1 semantics:
# state grant priority cutoff before the federal cutoff).
STATE_GRANT_DEADLINE = "2027-04-15T00:00:00Z"
FEDERAL_DEADLINE = "2028-06-30T00:00:00Z"
ACADEMIC_YEAR = "2027-2028"

# Event windows used across fixtures (all strictly after the clock default).
EVENT_START = "2026-09-10T10:00:00Z"
EVENT_END_2H = "2026-09-10T12:00:00Z"

# Recognition-rank percentiles (PRD §3.10).
GOLD_PERCENTILE = 70
SILVER_PERCENTILE = 40

TEST_DEFAULTS = {
    "TOTAL_BUDGET_CENTS": 100_000,
    "EVENT_COST_CENTS": 1_000,
    "EVENT_CAPACITY": 10,
}
