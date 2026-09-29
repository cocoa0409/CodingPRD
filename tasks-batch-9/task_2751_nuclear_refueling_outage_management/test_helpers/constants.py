"""Domain constants for the nuclear refueling outage management API.

Every value here is taken verbatim from the PRD; nothing is invented.
"""

# --- Logical clock (PRD 2.4) -------------------------------------------------
# "reads exactly 2026-08-01T00:00:00Z" before the clock has ever been set.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- Pagination (PRD 2.3) ---------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Work order priority scoring (PRD 3.2) ---------------------------------
WO_TYPE_WEIGHTS = {
    "MAINTENANCE": 20,
    "MODIFICATION": 35,
    "INSPECTION": 30,
}
SAFETY_FUNCTION_BONUS = 25
REGULATORY_COMMITMENT_BONUS = 20
DURATION_PRESSURE_MULTIPLIER = 300
DURATION_PRESSURE_CEILING = 30
DOSE_PENALTY_BLOCK_MREM = 100
DOSE_PENALTY_CEILING = 15

PRIORITY_CRITICAL_MIN_SCORE = 75
PRIORITY_HIGH_MIN_SCORE = 45

# --- Contingency factors for the critical path walk (PRD 3.4) --------------
UNLINKED_CONTINGENCY_PCT = 0.10
PRIORITY_CONTINGENCY_PCT = {
    "CRITICAL": 0.25,
    "HIGH": 0.15,
    "DISCRETIONARY": 0.05,
}

# --- Schedule posture (PRD 3.4) -------------------------------------------
AT_RISK_CEILING_MULTIPLIER = 1.10

# --- Scope cost rollup tiers (PRD 3.2) ------------------------------------
CONTINGENCY_TIER_1_CEILING_USD = 5000000
CONTINGENCY_TIER_2_CEILING_USD = 20000000
CONTINGENCY_RATE_TIER_1 = 0.08
CONTINGENCY_RATE_TIER_2 = 0.12
CONTINGENCY_RATE_TIER_3 = 0.15

# --- Core load pattern reactivity (PRD 3.3) -------------------------------
BASE_SHUTDOWN_MARGIN_PCM = 800
PCM_PER_FRESH_ASSEMBLY = 12
PCM_PER_GWD_MTU = 15
MIN_SHUTDOWN_MARGIN_PCM = 1000

# --- Radiological work permits (PRD 3.7) ----------------------------------
CONTINGENCY_DOSE_PCT = 0.20
ALARA_REVIEW_THRESHOLD_MREM = 300
ALARA_RESTRICTED_HOLD_MREM = 200
ALARA_RESTRICTED_RATIO = 0.25
MIN_SHIELDING_FACTOR = 0
MAX_SHIELDING_FACTOR = 0.95

# --- Startup testing (PRD 3.9) --------------------------------------------
REACTIVITY_TOLERANCE_PCM = 100

# --- Post-outage review weights (PRD 3.9) ---------------------------------
DURATION_VARIANCE_WEIGHT = 0.5
DOSE_VARIANCE_WEIGHT = 0.3
COST_VARIANCE_WEIGHT = 0.2
PERFORMANCE_INDEX_BASE = 100

# --- Field length bounds ---------------------------------------------------
MAX_AREA_CODE_LEN = 32
MAX_DESIGNATION_LEN = 32
MAX_TITLE_LEN = 200
MAX_LABEL_LEN = 200
MAX_TRAIN_LABEL_LEN = 8
MAX_FULL_NAME_LEN = 120
MAX_CONTRACTOR_LEN = 120
MAX_BADGE_NUMBER_LEN = 24
MAX_TEST_CODE_LEN = 32
MAX_ALARA_REFERENCE_LEN = 64
MAX_NRC_RELEASE_REFERENCE_LEN = 64
MAX_DESCRIPTION_LEN = 500
MAX_REVIEW_NOTES_LEN = 2000

# --- Literal cascade reasons (PRD 3.2, 3.6, 3.7, 3.8) ---------------------
REASON_WORK_ORDER_DEFERRED = "WORK_ORDER_DEFERRED"
REASON_SCOPE_LOCK_AUTO_DEFERRAL = "SCOPE_LOCK_AUTO_DEFERRAL"
REASON_SCHEDULE_POSTURE_AUTO_DEFERRAL = "SCHEDULE_POSTURE_AUTO_DEFERRAL"
EMERGENT_TITLE_PREFIX = "EMERGENT: "

# --- Defaults (PRD 3.2, 3.8) ----------------------------------------------
DEFAULT_REQUIRED_TRAINING_MODULES = 4
DEFAULT_REQUIRED_BADGED_WORKERS = 0
