"""Domain thresholds and defaults — numeric constants named in the PRD."""

# The logical clock's startup value (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Graduation requirement snapshot taken at audit creation (PRD §3.7).
GRADUATION_CREDITS_REQUIRED = 24

# Readiness grade-band weights (PRD §3.2).
READINESS_WEIGHTS_GRADE_12 = {
    "align": 0.30, "milestone": 0.40, "wbl": 0.20, "cert": 0.10,
}
READINESS_WEIGHTS_LOWER = {
    "align": 0.50, "milestone": 0.20, "wbl": 0.20, "cert": 0.10,
}
READINESS_CAP = 100

# Alignment / milestone empty-pool conventions (PRD §3.2, §3.4).
EMPTY_REQUIRED_ALIGNMENT = 100
EMPTY_MILESTONE_POOL_PCT = 100

# Certification points ladder (PRD §3.6).
CERT_POINTS_FULL = 100
CERT_POINTS_PARTIAL = 50
CERT_POINTS_NONE = 0

# Work-based-learning progress cap (PRD §3.6).
WBL_PCT_CAP = 100

# Caseload weights (PRD §3.1).
CASELOAD_WEIGHT_SENIOR = 2.0
CASELOAD_WEIGHT_JUNIOR = 1.5
CASELOAD_WEIGHT_OTHER = 1.0
CASELOAD_WEIGHT_NO_ACTIVE_PLAN = 0.5

# Frequently reused instants. All deadline/due/exam values lie strictly after
# the default clock; term windows may straddle it.
TEST_DEFAULTS = {
    "ADVISOR_MAX_CASELOAD": 50,
    "TEACHER_MAX_LETTERS": 5,
    "SITE_MAX_CONCURRENT": 10,
    "APPLICATION_DEADLINE": "2026-06-15T00:00:00Z",
    "MILESTONE_DUE": "2026-06-01T00:00:00Z",
    "REC_DUE": "2026-06-01T00:00:00Z",
    "EXAM_AT": "2026-05-10T09:00:00Z",
    "TERM_START": "2026-04-01T00:00:00Z",
    "TERM_END": "2026-06-01T00:00:00Z",
    "TERM": "2026-SPRING",
    "REPORTED_AT": "2026-05-02T00:00:00Z",
}

# The three milestone kinds seeded automatically on application creation
# (PRD §3.4).
SEEDED_MILESTONE_KINDS = ("ESSAY", "TRANSCRIPT", "FEE_PAYMENT")
