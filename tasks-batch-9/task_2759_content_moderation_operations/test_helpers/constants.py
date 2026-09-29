"""Domain constants for the Content Moderation Operations API.

Every value here is stated in the PRD; nothing is invented. Grouped by the
PRD concept it belongs to so a test reads in domain language rather than in
magic numbers.
"""

# ---------------------------------------------------------------------------
# Routing prefix and envelope
# ---------------------------------------------------------------------------

API_PREFIX = "/moderation"

# "meta.api_request_id" is a server-generated identifier prefixed "req_".
API_REQUEST_ID_PREFIX = "req_"

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

# "Before any operator moves it, the logical clock reads exactly
# 2026-08-01T00:00:00Z".
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# The instant almost every scenario in this suite opens at.
CLOCK_T0 = "2026-08-01T09:00:00Z"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Numeric precision
# ---------------------------------------------------------------------------

RATE_DECIMAL_PLACES = 4
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_TRUST_SAFETY_ADMIN = "TrustSafetyAdmin"
ROLE_POLICY_MANAGER = "PolicyManager"
ROLE_REVIEWER = "Reviewer"
ROLE_QA_AUDITOR = "QAAuditor"
ROLE_LEGAL_COUNSEL = "LegalCounsel"
ROLE_ACCOUNT_HOLDER = "AccountHolder"

ALL_ROLES = (
    ROLE_TRUST_SAFETY_ADMIN,
    ROLE_POLICY_MANAGER,
    ROLE_REVIEWER,
    ROLE_QA_AUDITOR,
    ROLE_LEGAL_COUNSEL,
    ROLE_ACCOUNT_HOLDER,
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

ACCOUNT_TIERS = ("STANDARD", "HIGH_PROFILE", "GOVERNMENT")
ACCOUNT_STANDINGS = ("GOOD_STANDING", "LIMITED", "SUSPENDED", "BANNED")

LANGUAGES = ("EN", "ES", "DE", "AR", "HI")
MEDIA_KINDS = ("TEXT", "IMAGE", "VIDEO")
VISIBILITY_STATUSES = ("LIVE", "AGE_GATED", "REMOVED", "REINSTATED")
REVIEW_STATUSES = ("CLEAR", "UNDER_REVIEW", "ACTIONED", "APPEALED")

SEVERITY_TIERS = ("T1", "T2", "T3", "T4")
SPECIALTIES = ("VIOLENCE", "CSAM_ADJACENT", "HATE", "SPAM", "MISINFO", "SELF_HARM")
CATEGORY_STATUSES = ("DRAFT", "ACTIVE")

ENFORCEMENT_ACTIONS = ("REMOVE", "AGE_GATE", "WARN")
DECISION_OUTCOMES = ("REMOVE", "AGE_GATE", "WARN", "NO_ACTION")
POLICY_VERSION_STATUSES = ("DRAFT", "BACKTESTING", "ACTIVE", "SUPERSEDED")

REVIEWER_ROLE_CLASSES = ("FRONTLINE", "SENIOR", "QA")
REVIEWER_STATUSES = ("ACTIVE", "ON_WELLNESS_BREAK", "PENDING_RETRAINING", "SUSPENDED")

CASE_STATUSES = ("PENDING_ASSIGNMENT", "ASSIGNED", "ESCALATED", "DECIDED")
CASE_ORIGINS = ("CLASSIFIER", "MANUAL_REPORT", "LEGAL_REQUEST")
DECISION_SOURCES = ("AUTO", "HUMAN", "LEGAL")
ESCALATION_REASONS = ("IMMINENT_HARM", "LEGAL_REQUEST", "HIGH_PROFILE", "CALIBRATION")

DISPOSITIONS = ("DISCARDED", "AUTO_ACTION", "HUMAN_REVIEW")

APPEAL_STATUSES = ("SUBMITTED", "INDEPENDENT_REVIEW", "UPHELD", "OVERTURNED")
APPEAL_RESOLUTIONS = ("UPHELD", "OVERTURNED")

AUDIT_SAMPLE_STATUSES = ("SAMPLED", "AUDITED", "DISPUTED")
AUDIT_VERDICTS = ("AGREE", "DISAGREE_MINOR", "DISAGREE_MATERIAL")
SAMPLING_REASONS = ("RANDOM", "TARGETED_LOW_ACCURACY", "POST_POLICY_CHANGE")

REPORT_STATUSES = ("DRAFT", "COMPUTED", "PUBLISHED")
REPORT_VARIANTS = ("PROVISIONAL", "RESTATED")

# ---------------------------------------------------------------------------
# Account standing breakpoints (inclusive)
# ---------------------------------------------------------------------------

STANDING_BANNED_AT = 10
STANDING_SUSPENDED_AT = 6
STANDING_LIMITED_AT = 3

# ---------------------------------------------------------------------------
# Account defaults
# ---------------------------------------------------------------------------

DEFAULT_APPEAL_CREDITS = 3
DEFAULT_TIER = "STANDARD"
DEFAULT_GRAPHIC_WEIGHT = 0

# ---------------------------------------------------------------------------
# Policy version defaults and gates
# ---------------------------------------------------------------------------

DEFAULT_APPEAL_WINDOW_HOURS = 72
DEFAULT_REVIEW_SLA_MINUTES = 240
DEFAULT_REQUIRES_RECERTIFICATION = True
MAX_BACKTEST_DIVERGENCE = 0.25

# ---------------------------------------------------------------------------
# effective_confidence
# ---------------------------------------------------------------------------

TIER_CONFIDENCE_MULTIPLIER = {
    "STANDARD": 1.00,
    "HIGH_PROFILE": 0.85,
    "GOVERNMENT": 0.80,
}
REPEAT_BONUS_PER_POINT = 0.01
REPEAT_BONUS_CAP_POINTS = 10

# ---------------------------------------------------------------------------
# strike_points_applied
# ---------------------------------------------------------------------------

SEVERITY_POINTS = {"T1": 8, "T2": 4, "T3": 2, "T4": 1}
ACTION_WEIGHT = {"REMOVE": 1.0, "AGE_GATE": 0.75, "WARN": 0.25, "NO_ACTION": 0.0}
REPEAT_MULTIPLIER_STEP = 0.25
REPEAT_MULTIPLIER_CAP_REMOVALS = 4

# ---------------------------------------------------------------------------
# Review deadlines
# ---------------------------------------------------------------------------

SEVERITY_SLA_DIVISOR = {"T1": 4, "T2": 2, "T3": 1, "T4": 1}
CONGESTION_LOW_MAX_OPEN = 5
CONGESTION_MID_MAX_OPEN = 15
CONGESTION_MULTIPLIER_LOW = 1.0
CONGESTION_MULTIPLIER_MID = 1.5
CONGESTION_MULTIPLIER_HIGH = 2.0
ESCALATION_SLA_MINUTES = 30
LEGAL_SLA_MINUTES = 1440

# ---------------------------------------------------------------------------
# Reviewer workforce
# ---------------------------------------------------------------------------

DEFAULT_MAX_CONCURRENT_CASES = 3
DEFAULT_DAILY_EXPOSURE_CAP_POINTS = 20
MEDIA_EXPOSURE_MULTIPLIER = {"TEXT": 1, "IMAGE": 2, "VIDEO": 3}
NULL_ACCURACY_RANK_VALUE = 1.0

# ---------------------------------------------------------------------------
# Accuracy gate
# ---------------------------------------------------------------------------

RETRAIN_FLOOR = 0.85
SUSPEND_FLOOR = 0.60
MIN_GATE_SAMPLE = 2

# ---------------------------------------------------------------------------
# Identifiers used for negative lookups
# ---------------------------------------------------------------------------

UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
