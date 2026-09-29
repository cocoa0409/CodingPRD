"""Domain thresholds and pinned constants taken from the PRD's arithmetic rules."""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# --------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Business-day arithmetic (PRD §2.7)
# --------------------------------------------------------------------------

HOLIDAYS = [
    "2026-11-26",
    "2026-11-27",
    "2026-12-24",
    "2026-12-25",
    "2027-01-01",
]

# --------------------------------------------------------------------------
# Committee composition and chair eligibility (PRD §3.3)
# --------------------------------------------------------------------------

DOCTORAL_MIN_MEMBERS = 5
DOCTORAL_MIN_EXTERNAL = 1
MASTERS_MIN_MEMBERS = 3
MAX_CHAIR_LOAD = 4

# --------------------------------------------------------------------------
# Defense scheduling (PRD §3.4)
# --------------------------------------------------------------------------

MIN_OCCUPATION_MINUTES = 30
MAX_OCCUPATION_MINUTES = 240
DEFAULT_TURNOVER_BUFFER_MINUTES = 30
DEFAULT_ANNOUNCEMENT_LEAD_BDAYS = 10

# --------------------------------------------------------------------------
# Severity-weighted defect score and revision windows (PRD §3.5)
# --------------------------------------------------------------------------

W_CRITICAL = 3.4
W_MAJOR = 1.65
W_MINOR = 0.35
DENSITY_BASE_PAGES = 100
MIN_DENSITY_PAGES = 50
REVISION_MANDATORY_THRESHOLD = 12.00

CYCLE1_WINDOW_BDAYS = 10
CYCLE2_WINDOW_BDAYS = 7
CYCLE3_PLUS_WINDOW_BDAYS = 5
LONG_DOC_BONUS_BDAYS = 2
LONG_DOC_PAGE_THRESHOLD = 300

FAIR_USE_MAX_WORDS = 400

# --------------------------------------------------------------------------
# Plagiarism screening (PRD §3.6)
# --------------------------------------------------------------------------

FLAG_THRESHOLD_PCT = 18.00
INTEGRITY_WITHHELD_REASON = "ACADEMIC_INTEGRITY_FINDING"
INTEGRITY_WITHHELD_NOTATION = "Degree withheld pending academic integrity resolution"
COMMITTEE_COMPOSITION_CHANGED = "COMMITTEE_COMPOSITION_CHANGED"

# --------------------------------------------------------------------------
# Embargo duration caps in months (PRD §3.7)
# --------------------------------------------------------------------------

DOCTORAL_EMBARGO_CAPS = {
    "PATENT_PENDING": 24,
    "PUBLISHER_AGREEMENT": 12,
    "SENSITIVE_DATA": 36,
    "HUMAN_SUBJECTS": 12,
}

MASTERS_EMBARGO_CAPS = {
    "PATENT_PENDING": 12,
    "PUBLISHER_AGREEMENT": 6,
    "SENSITIVE_DATA": 18,
    "HUMAN_SUBJECTS": 6,
}

# --------------------------------------------------------------------------
# Repository metadata and late fee (PRD §3.8)
# --------------------------------------------------------------------------

W_ABSTRACT = 0.30
W_KEYWORDS = 0.20
W_ADVISOR = 0.15
W_DEPARTMENT = 0.15
W_DEGREE_LEVEL = 0.10
W_DOCUMENT_TYPE = 0.10
METADATA_TOTAL_WEIGHT = 1.00

ABSTRACT_MIN_WORDS = 150
KEYWORDS_MIN_COUNT = 3
METADATA_MIN_SCORE = 0.85

GRACE_HIGH_TURNAROUND_BDAYS = 15
GRACE_HIGH_BDAYS = 5
GRACE_MID_TURNAROUND_BDAYS = 10
GRACE_MID_BDAYS = 3
DAILY_LATE_FEE_CENTS = 2500
LATE_FEE_CAP_CENTS = 50000
