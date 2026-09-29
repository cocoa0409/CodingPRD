"""Domain thresholds — the numeric constants the PRD's calculations pin.

Every figure here is quoted from PRD §2.7, §2.8, §2.12, §3.4, §3.5, §3.6, §3.7,
§3.8 and §3.9.  Tests import these rather than repeating magic numbers.
"""

# ------------------------------------------------ logical clock (PRD §2.5)
# "On start-up the logical clock reads exactly 2026-08-01T00:00:00Z".
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# ------------------------------------- stipend commitment (PRD §3.6, §2.8)
HAZARD_UPLIFT_PCT = 0.10
EXCLUSIVITY_PREMIUM_PER_30D_CENTS = 40_000
EXCLUSIVITY_BLOCK_DAYS = 30
PRESS_APPEARANCE_RATE_CENTS = 25_000
REUNION_FLAT_CENTS = 150_000
PROVISIONAL_PRESS_RESERVE = 2

DEPICTION_ADJ_PCT = {
    "FULL": 0.00,
    "LIMITED": -0.05,
    "PSEUDONYMIZED": -0.12,
}

# "a count of 4 or fewer takes a multiplier of 1.00, a count from 5 to 8
#  inclusive takes 1.15, and a count of 9 or more takes 1.30"
TIER_MULTIPLIER_LOW = 1.00
TIER_MULTIPLIER_MID = 1.15
TIER_MULTIPLIER_HIGH = 1.30
TIER_BOUNDARY_LOW_MAX_EPISODES = 4
TIER_BOUNDARY_MID_MAX_EPISODES = 8

# ------------------------------------------------- risk scoring (PRD §3.4)
KIND_WEIGHT = {
    "INTERVIEW": 1.5,
    "BACKGROUND_CHECK": 3.0,
    "PSYCH_EVAL": 4.0,
    "MEDICAL_EXAM": 2.0,
}
OUTCOME_FACTOR = {
    "PASS": 0.0,
    "CONDITIONAL": 0.5,
    "FAIL": 1.0,
}
PENDING_SEVERITY_CEILING = 5
DECAY_LADDER = [1.00, 0.80, 0.60, 0.50]
DECAY_TAIL_FACTOR = 0.50
RISK_REJECT_THRESHOLD = 12.00
RISK_ENHANCED_SUPPORT_THRESHOLD = 8.00

# Validity windows in days; INTERVIEW never expires (PRD §3.4).
SCREENING_VALIDITY_DAYS = {
    "MEDICAL_EXAM": 30,
    "PSYCH_EVAL": 60,
    "BACKGROUND_CHECK": 180,
    "INTERVIEW": None,
}

# ------------------------------------------- welfare commitment (PRD §3.7)
WELFARE_BAND_LOW_RATE = 0.04
WELFARE_BAND_MID_RATE = 0.07
WELFARE_BAND_HIGH_RATE = 0.09
WELFARE_BAND_MID_FLOOR_CENTS = 5_000_000
WELFARE_BAND_HIGH_FLOOR_CENTS = 20_000_000

TIER_FACTOR = {
    "STANDARD": 1.0,
    "ENHANCED": 1.5,
    "CRITICAL": 2.0,
}

# ----------------------------------------------- casting posture (PRD §2.7)
RESTRICTED_UTILISATION_NUMERATOR = 90
RESTRICTED_UTILISATION_DENOMINATOR = 100
FROZEN_INCIDENT_COUNT = 2

# --------------------------------- jurisdictional minimums (PRD §2.12)
MIN_EDUCATION_HOURS_BY_JURISDICTION = {
    "CA": 15,
    "NY": 12,
    "GA": 10,
    "IL": 12,
}
MIN_TRUST_PCT_BY_JURISDICTION = {
    "CA": 0.15,
    "NY": 0.15,
    "GA": 0.10,
    "IL": 0.10,
}

# ---------------------------------------- minor on-set hours (PRD §3.8)
MINOR_DAILY_TOTAL_HOURS_CAP = 8.0
EDUCATION_DAYS_PER_WEEK = 5

# ------------------------------- post-production obligations (PRD §3.9)
PRESS_SPACING_DAYS = 30
REUNION_OFFSET_DAYS = 180

# ------------------------------------ aftercare authorisation (PRD §3.9)
BASE_SESSIONS_BY_SEVERITY = {1: 2, 2: 4, 3: 8, 4: 12, 5: 16}
AFTERCARE_SESSION_CAP = 24

# ------------------------------------------------ pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# ------------------------------------------------------- test defaults
TEST_DEFAULTS = {
    "PHOTOGRAPHY_START_UTC": "2026-09-15T00:00:00Z",
    "PHOTOGRAPHY_END_UTC": "2026-12-15T00:00:00Z",
    "ADULT_DOB": "1994-04-02",
    "MINOR_DOB": "2011-05-20",
    "STIPEND_POOL_CENTS": 50_000_000,
    "WELFARE_BUDGET_CENTS": 10_000_000,
}

# A syntactically valid UUID that never names a persisted record.
UNKNOWN_UUID = "ffffffff-ffff-4fff-8fff-ffffffffffff"
