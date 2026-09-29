"""Domain constants for the Artist Residency Program Administration API."""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Host country / internationality
# ---------------------------------------------------------------------------
HOST_COUNTRY = "US"

# ---------------------------------------------------------------------------
# Panel rubric
# ---------------------------------------------------------------------------
RUBRIC_WEIGHT_ARTISTIC_MERIT = 35
RUBRIC_WEIGHT_FEASIBILITY = 27
RUBRIC_WEIGHT_COMMUNITY_FIT = 23
RUBRIC_WEIGHT_TECHNICAL_READINESS = 15
RUBRIC_SCORE_MIN = 0
RUBRIC_SCORE_MAX = 10
EXPERTISE_MATCH_MULTIPLIER = 1.00
EXPERTISE_MISMATCH_MULTIPLIER = 0.90
TRIM_MIN_PANELISTS = 4

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
MAX_REVISION_ROUNDS = 2
FEE_WAIVER_INCOME_CEILING_CENTS = 3500000
PROJECT_STATEMENT_MAX_LEN = 4000

# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
MIN_SESSION_WEEKS = 4
MAX_SESSION_WEEKS = 16

# ---------------------------------------------------------------------------
# Stipends and withholding
# ---------------------------------------------------------------------------
STIPEND_PERIOD_WEEKS = 2
WITHHOLDING_EXEMPT_THRESHOLD_CENTS = 60000
NRA_WITHHOLDING_RATE = 0.30
TREATY_WITHHOLDING_RATE = 0.15
DOMESTIC_WITHHOLDING_RATE = 0.00

# ---------------------------------------------------------------------------
# Visa timeline
# ---------------------------------------------------------------------------
VISA_LEAD_DAYS = 90
VISA_EARLIEST_ENTRY_LEAD_DAYS = 30
VISA_BACKLOG_DAYS_DEFAULT = 21
VISA_BACKLOG_DAYS_HIGH_VOLUME = 45
HIGH_VOLUME_VISA_COUNTRIES = ["IN", "CN", "NG", "BR"]
VISA_J1_MIN_SESSION_WEEKS = 9

# ---------------------------------------------------------------------------
# Facilities
# ---------------------------------------------------------------------------
STUDIO_TURNAROUND_DAYS = 2
VENTILATION_RANK = {"NONE": 0, "LOCAL": 1, "FUME_HOOD": 2}
CAPABILITY_TAGS = [
    "WELDING",
    "KILN",
    "DARKROOM",
    "WET_LAB",
    "PRINT_PRESS",
    "CLEAN_ONLY",
]
VENTILATION_CLASSES = ["NONE", "LOCAL", "FUME_HOOD"]
STUDIO_STATUSES = ["AVAILABLE", "MAINTENANCE", "DECOMMISSIONED"]
HOUSING_UNIT_STATUSES = ["AVAILABLE", "MAINTENANCE"]
ACCESSIBILITY_FEATURES = [
    "STEP_FREE",
    "ROLL_IN_SHOWER",
    "VISUAL_ALARM",
    "GROUND_FLOOR",
]

# ---------------------------------------------------------------------------
# Obligations
# ---------------------------------------------------------------------------
OBLIGATION_OPEN_STUDIO_BASE = 1
OBLIGATION_EXHIBITION_BASE = 1
OBLIGATION_ARTIST_TALK_BASE = 1
OBLIGATION_WORKSHOP_WEEKS_PER_UNIT = 4
OBLIGATION_TYPES = [
    "OPEN_STUDIO",
    "EXHIBITION",
    "ARTIST_TALK",
    "COMMUNITY_WORKSHOP",
]

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
CYCLE_STAGES = [
    "DRAFT",
    "OPEN",
    "SCREENING",
    "PANEL_REVIEW",
    "SLATE_LOCKED",
    "CLOSED",
]
APPLICATION_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "REVISION_REQUESTED",
    "PANEL_REVIEW",
    "SCORED",
    "OFFERED",
    "WAITLISTED",
    "REJECTED",
    "ACCEPTED",
    "DECLINED",
]
APPLICATION_TERMINAL_STATUSES = ["REJECTED", "ACCEPTED", "DECLINED"]
FEE_STATUSES = ["PENDING", "PAID", "WAIVED"]
MEDIA_TYPES = ["IMAGE", "VIDEO", "AUDIO", "TEXT", "MODEL_3D"]
PANELIST_STATUSES = ["ACTIVE", "RECUSED_FOR_CYCLE", "INACTIVE"]
PANEL_ASSIGNMENT_STATUSES = [
    "ASSIGNED",
    "SCORED",
    "CONFLICT_DECLARED",
    "VACATED",
]
CONFLICT_TYPES = [
    "SAME_AFFILIATION",
    "PRIOR_MENTORSHIP",
    "FAMILIAL",
    "FINANCIAL",
]
SEVERE_CONFLICT_TYPES = ["FAMILIAL", "FINANCIAL"]
RESIDENCY_STATUSES = [
    "SCHEDULED",
    "IN_RESIDENCE",
    "COMPLETED",
    "TERMINATED",
    "WITHDRAWN",
]
COMPLIANCE_STATUSES = ["TRAINING_PENDING", "CLEARED", "SUSPENDED"]
ASSIGNMENT_STATUSES = ["ACTIVE", "RELEASED"]
SELECTION_MODES = ["EXPLICIT", "AUTO_SELECTED"]
VISA_STATUSES = [
    "INITIATED",
    "DOCS_REQUESTED",
    "DOCS_SUBMITTED",
    "FILED",
    "APPROVED",
    "DENIED",
]
VISA_CASE_TYPES = ["B1_SHORT_TERM", "J1_RESEARCH_SCHOLAR"]
DISBURSEMENT_STATUSES = ["SCHEDULED", "PAID", "VOIDED", "REVERSED"]
OBLIGATION_STATUSES = ["PENDING", "SATISFIED", "WAIVED", "BREACHED"]
TAX_FORM_TYPES = ["W9", "1042S"]
STIPEND_BASES = ["PROVISIONAL", "FINAL_SETTLED"]
TRAINING_TYPES_BASE = ["SAFETY_ORIENTATION", "HAZMAT_HANDLING"]

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
