"""Domain thresholds — numeric constants from PRD §3 calculation rules."""

# Normalized grade (PRD §3.3 step 1)
NORMALIZE = {
    "CENTER": 5.0,
    "SCALE": 1.5,
    "MIN_G": 1.0,
    "MAX_G": 9.0,
}

# Tier thresholds (PRD §3.3 step 2)
TIER = {
    "T1_MIN": 8.00,
    "T2_MIN": 7.00,
    "T3_MIN": 6.00,
}

# Fit score (PRD §3.5)
FIT = {
    "DEFAULT_BASE": 20.0,
    "MEDICAL_HIGH_MULT": 0.8,
    "CHAR_DEDUCTION": 15.0,
    "BASE_NEED": {"P1": 90.0, "P2": 70.0, "P3": 50.0, "P4": 30.0},
    "MIN": 0.0,
    "MAX": 100.0,
}

# Budget posture (PRD §3.7)
POSTURE_FRACTION = 0.10

# Facility buffer (PRD §3.8)
FACILITY_BUFFER_MINUTES = 30

# Scout evaluation (PRD §3.9)
SCOUT_EVAL = {
    "HIT_GRADE_MIN": 7.00,
    "HIT_OUTCOME_MIN": 70,
    "RMSE_PENALTY": 10,
}

# Pagination (PRD §2.3)
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}
