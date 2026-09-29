"""Numeric and temporal constants stated by the PRD."""

# ---- Logical clock --------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# ---- Pagination -----------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---- Firm risk posture ----------------------------------------------------
CRITICAL_RISK_COUNT_FOR_CRITICAL = 3
OPEN_DEFICIENCY_COUNT_FOR_ELEVATED = 5

# ---- Partner EQR eligibility ---------------------------------------------
CPE_HOURS_MINIMUM = 120
COOLING_OFF_DAYS = 730
EQR_CAPACITY_LIMIT = 3

# ---- Engagement risk score -----------------------------------------------
ENGAGEMENT_TYPE_BASE_RISK = {
    "AUDIT": 20,
    "REVIEW": 8,
    "ATTESTATION": 6,
    "ERISA_AUDIT": 30,
    "SINGLE_AUDIT": 32,
    "BROKER_DEALER": 28,
}
FIRST_YEAR_CLIENT_RISK = 15
PUBLIC_INTEREST_RISK = 12
PRIOR_FINDING_RISK_PER_FINDING = 4
PRIOR_FINDING_RISK_CAP = 20
LOAD_PENALTY_PER_ENGAGEMENT = 3
LOAD_PENALTY_THRESHOLD = 8
SPECIALIZATION_CREDIT = -10
RISK_SCORE_MIN = 0
RISK_SCORE_MAX = 100
EQR_REQUIRED_RISK_SCORE = 70

MUST_SELECT_ENGAGEMENT_TYPES = ("ERISA_AUDIT", "SINGLE_AUDIT", "BROKER_DEALER")

SPECIALIZATION_FOR_TYPE = {
    "ERISA_AUDIT": "EBP",
    "SINGLE_AUDIT": "GOVERNMENT",
    "BROKER_DEALER": "BROKER_DEALER",
}

# ---- Engagement file / documentation -------------------------------------
DOCUMENTATION_WINDOW_DAYS = 60

# ---- Quality risk residual scoring ---------------------------------------
DESIGN_BASIS_EFFECTIVE_REDUCTION = 0.35
DESIGN_BASIS_PARTIAL_REDUCTION = 0.20
DESIGN_BASIS_REDUCTION_CAP = 0.80
OPERATING_BASIS_EFFECTIVE_FACTOR = 0.30
OPERATING_BASIS_PARTIAL_FACTOR = 0.10
SEVERITY_BAND_CRITICAL_MIN = 15.00
SEVERITY_BAND_HIGH_MIN = 8.00
SEVERITY_BAND_MODERATE_MIN = 4.00

# ---- Inspection findings --------------------------------------------------
CLASS_POINTS = {
    "OBSERVATION": 0,
    "DEFICIENCY": 3,
    "SIGNIFICANT_DEFICIENCY": 8,
    "MATERIAL_FAILURE": 20,
}

# ---- Root cause analysis --------------------------------------------------
RCA_FACTOR_MULTIPLIER = 2
RCA_METHOD_BONUS = {"FIVE_WHYS": 2, "FISHBONE": 3, "PARETO": 1}
RCA_RECURRENCE_BONUS = 2
RCA_DEPTH_SCORE_CAP = 10

# ---- Remediation plan scoring --------------------------------------------
DEPTH_WEIGHT = 0.40
SPECIFICITY_WEIGHT = 0.35
COMPLETION_WEIGHT = 0.25
TIER_STANDARD_MIN = 5.00
TIER_STRONG_MIN = 8.00
LATE_PENALTY_RATE = {"CRITICAL": 0.15, "STANDARD": 0.10, "STRONG": 0.05}
ACCEPTANCE_THRESHOLD = 7.00

# ---- Peer review scope hours ---------------------------------------------
SCOPE_HOUR_TIERS = ((500, 16), (2000, 24), (10000, 40))
SCOPE_HOURS_ABOVE_TOP_TIER = 64
CATEGORY_HOURS = {
    "ERISA_AUDIT": 8,
    "SINGLE_AUDIT": 10,
    "BROKER_DEALER": 8,
    "GOVERNMENTAL": 6,
    "PUBLIC_INTEREST": 12,
}
POSTURE_UPLIFT = {"CRITICAL": 0.25, "ELEVATED": 0.10, "STABLE": 0.00}

# ---- Peer review scheduling ----------------------------------------------
TRAVEL_BUFFER_DAYS = 5
MONITORING_VISIT_DUE_DAYS = 90
PREISSUANCE_REVIEW_DUE_DAYS = 45
FOLLOW_UP_START_OFFSET_DAYS = 180
FOLLOW_UP_WINDOW_LENGTH_DAYS = 14
