"""Domain thresholds and numeric constants stated in PRD §2.5, §3.3-§3.8."""

# Logical clock default (PRD §2.5).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Modified Atwater metabolizable-energy constants (PRD §3.3).
ASH_PCT_ASSUMED = 7.0
PROTEIN_GE = 5.7
FAT_GE = 9.4
CARB_GE = 4.1
DIGEST_BASE = 87.8
DIGEST_FIBER_COEF_FORMULATION = 0.88
DIGEST_FIBER_COEF_LAB = 0.44

# AAFCO nutrient floors by species / life-stage group (PRD §3.3).
AAFCO_MIN = {
    ("DOG", "ADULT_MAINTENANCE"): {"protein": 18.0, "fat": 5.5, "calcium": 0.6, "phosphorus": 0.5},
    ("DOG", "GROWTH"): {"protein": 22.5, "fat": 8.5, "calcium": 1.0, "phosphorus": 0.8},
    ("CAT", "ADULT_MAINTENANCE"): {"protein": 26.0, "fat": 9.0, "calcium": 0.6, "phosphorus": 0.5},
    ("CAT", "GROWTH"): {"protein": 30.0, "fat": 9.0, "calcium": 1.0, "phosphorus": 0.8},
}
ME_NORMALIZATION_REF = 4000

# Guaranteed-analysis composite weights (PRD §3.6).
WEIGHT_COMPOSITE = 1.25
WEIGHT_SPOT = 1

# Deviation-index weights (PRD §3.6).
W_PROTEIN = 3.0
W_FAT = 2.0
W_FIBER = 1.5
W_MOISTURE = 1.0

# Yield-variance hold threshold (PRD §3.6) — strict greater-than.
YIELD_HOLD_THRESHOLD_PCT = 5.00

# Registration fee schedule (PRD §3.7).
STATE_BASE_FEE_CENTS = {"CA": 7500, "TX": 6000, "NY": 8000}
DEFAULT_BASE_FEE_CENTS = 5000
T2_MULTIPLIER = 1.5
T3_MULTIPLIER = 2.0

# Complaint risk model (PRD §3.8).
SEVERITY_WEIGHT = {"MINOR": 5, "SERIOUS": 20, "LIFE_THREATENING": 45, "DEATH": 60}
CATEGORY_WEIGHT = {
    "PALATABILITY": 2,
    "PACKAGING": 3,
    "LABEL_DEFECT": 8,
    "FOREIGN_MATERIAL": 12,
    "ILLNESS": 15,
}
ADVERSE_EVENT_BONUS = 10
ESCALATION_THRESHOLD = 60.0
REGISTRATION_HOLD_THRESHOLD = 70.0
ROLLUP_WINDOW_DAYS = 90
DECAYED_SHARE = 0.25
DECAY_WINDOW_DAYS = 30

# Feeding-trial rules (PRD §3.4).
TRIAL_MIN_ANIMALS_ADULT = 8
TRIAL_MIN_DURATION_DAYS_ADULT = 26
TRIAL_PASS_RATIO = 0.75

# Inclusion-sum tolerance (PRD §3.3).
INCLUSION_SUM_TARGET = 100.00
INCLUSION_SUM_TOLERANCE = 0.01

TEST_DEFAULTS = {
    "PLANNED_KG": 500.0,
    "BEST_BY_DATE": "2027-08-01T00:00:00Z",
}
