"""The fixed numbers the PRD's calculations are built on."""

# --------------------------------------------------------------------------
# The logical clock (PRD §2.5)
# --------------------------------------------------------------------------
CLOCK_STARTUP = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Course water posture (PRD §2.10, §3.1)
# --------------------------------------------------------------------------
DEFAULT_RESTRICTED_THRESHOLD_PCT = 80
DEFAULT_SUSPENDED_THRESHOLD_PCT = 100

# --------------------------------------------------------------------------
# The tiered water overage assessment (PRD §3.1)
# --------------------------------------------------------------------------
BASE_RATE_PER_KGAL = 3.25
TIER_T2_FLOOR = 25.00
TIER_T3_FLOOR = 100.00
SURCHARGE_RATE_T1 = 0.90
SURCHARGE_RATE_T2 = 1.40
SURCHARGE_RATE_T3 = 2.10
SURCHARGE_RATE_BY_TIER = {
    "T1": SURCHARGE_RATE_T1,
    "T2": SURCHARGE_RATE_T2,
    "T3": SURCHARGE_RATE_T3,
}

# --------------------------------------------------------------------------
# Nitrogen (PRD §3.3, §3.4)
# --------------------------------------------------------------------------
SQ_FT_PER_ACRE = 43560
MAX_N_LB_PER_1000_BY_AREA_TYPE = {
    "GREEN": 4.00,
    "PRACTICE_GREEN": 4.00,
    "TEE": 5.00,
    "APPROACH": 5.00,
    "FAIRWAY": 6.00,
    "ROUGH": 3.00,
}
MAX_PLAN_RETURNS = 2

# --------------------------------------------------------------------------
# Irrigation (PRD §3.5)
# --------------------------------------------------------------------------
GAL_PER_PCT_PER_1000SQFT = 6.2
POSTURE_FACTOR_OPEN = 1.00
POSTURE_FACTOR_RESTRICTED = 0.60
POSTURE_FACTOR_SUSPENDED = 0.00
POSTURE_FACTOR_BY_POSTURE = {
    "OPEN": POSTURE_FACTOR_OPEN,
    "RESTRICTED": POSTURE_FACTOR_RESTRICTED,
    "SUSPENDED": POSTURE_FACTOR_SUSPENDED,
}

# --------------------------------------------------------------------------
# Crew windows and interval geometry (PRD §2.11, §3.6)
# --------------------------------------------------------------------------
PLAY_CLEARANCE_BUFFER_MINUTES = 30
HOLE_PACE_MINUTES = 12
MAX_WINDOW_DEFERRALS = 2

# --------------------------------------------------------------------------
# Frost release and tournament readiness (PRD §3.7)
# --------------------------------------------------------------------------
MIN_SEPARATION_MINUTES = 10
TARGET_SPEED_FT = 11.0
TOLERANCE_SPEED_FT = 1.5
TARGET_FIRMNESS = 1.35
TOLERANCE_FIRMNESS = 0.30
TARGET_MOISTURE_PCT = 18.0
TOLERANCE_MOISTURE = 6.0
W_SPEED = 0.50
W_FIRM = 0.30
W_MOIST = 0.20
MIN_GREENS_MEASURED = 3
READINESS_WINDOW_HOURS = 24
CERT_THRESHOLD = 82.00

# --------------------------------------------------------------------------
# The replacement score (PRD §3.8)
# --------------------------------------------------------------------------
W_USAGE = 0.45
W_AGE = 0.35
W_OVERDUE = 0.20
EXPECTED_AGE_LIFE_YEARS = 10
REPLACEMENT_FLAG_THRESHOLD = 70

# --------------------------------------------------------------------------
# Comparison tolerances for the fixed decimal scales of PRD §2.6
# --------------------------------------------------------------------------
TOLERANCE_1DP = 0.01
TOLERANCE_2DP = 0.01
TOLERANCE_3DP = 0.0005
