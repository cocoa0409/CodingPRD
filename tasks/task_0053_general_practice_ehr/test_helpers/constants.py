"""Domain thresholds — numeric constants from the PRD's pricing, eligibility,
and workflow rules. Generic NON_EXISTENT_UUID comes from the framework.
"""

# E/M tiered multiplier selected by em_level (PRD Section 3.3).
EM_LEVEL_MULTIPLIER = {
    1: 0.5,
    2: 0.8,
    3: 1.0,
    4: 1.4,
    5: 2.0,
}

# Contractual write-down rate applied to the provisional sum at finalize
# (PRD Section 3.5: multiply by (1 - 0.10) = 0.90).
CONTRACTUAL_ADJ_RATE = 0.10

# Referral authorization windows in whole days (PRD Section 3.8).
ROUTINE_AUTH_DAYS = 90
URGENT_AUTH_DAYS = 14

# Vaccine minimum spacing in days (PRD Section 3.5).
VACCINE_MIN_INTERVAL_DAYS = 28

# Portal lockout threshold (PRD Section 3.9).
PORTAL_LOCKOUT_THRESHOLD = 3

# Adherence minimum number of fills (PRD Section 3.7).
MED_ADHERENCE_MIN_FILLS = 1

# The fixed reporting year used for open_care_gaps (PRD Section 3.2).
CURRENT_MEASUREMENT_YEAR = 2026

# Inclusive HEDIS age windows by measure type (PRD Section 3.10).
MEASURE_AGE_WINDOW = {
    "CIS_FLU": {"min_age": 0, "max_age": 18},
    "BCS_MAMMOGRAM": {"min_age": 50, "max_age": 74},
    "CBP_BP_CONTROL": {"min_age": 18, "max_age": 85},
    "MED_ADHERENCE": {"min_age": 18, "max_age": 120},
}

THRESHOLDS = {
    "CONTRACTUAL_ADJ_RATE": CONTRACTUAL_ADJ_RATE,
    "ROUTINE_AUTH_DAYS": ROUTINE_AUTH_DAYS,
    "URGENT_AUTH_DAYS": URGENT_AUTH_DAYS,
    "VACCINE_MIN_INTERVAL_DAYS": VACCINE_MIN_INTERVAL_DAYS,
    "PORTAL_LOCKOUT_THRESHOLD": PORTAL_LOCKOUT_THRESHOLD,
    "MED_ADHERENCE_MIN_FILLS": MED_ADHERENCE_MIN_FILLS,
    "CURRENT_MEASUREMENT_YEAR": CURRENT_MEASUREMENT_YEAR,
    "DEFAULT_PANEL_CAPACITY": 2000,
}
