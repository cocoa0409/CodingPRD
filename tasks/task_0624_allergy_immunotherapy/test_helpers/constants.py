"""Domain thresholds — numeric constants from the PRD's clinical calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# --- IgE class boundaries (PRD section 3.2) ---------------------------------
IGE_CLASS_BOUNDS_KU = [0.35, 0.70, 3.5, 17.5, 50, 100]
SKIN_POSITIVE_DIFF_MM = 3

# --- Recommended-tier thresholds (PRD section 3.2) --------------------------
TIER_MODERATE_FLOOR = 4
TIER_HIGH_FLOOR = 7

# --- Dilution factors by color (PRD section 2.9) ----------------------------
DILUTION_BY_COLOR = {
    "GREEN": 0.001,
    "YELLOW": 0.01,
    "RED": 0.1,
    "SILVER": 1.0,
}
STANDARD_POTENCY_PNU_PER_ML = 10000

# --- Build-up ladder step volumes (PRD section 3.6) -------------------------
BUILD_UP_STEPS = {
    "GREEN": [0.10, 0.20, 0.40],
    "YELLOW": [0.10, 0.20, 0.40],
    "RED": [0.10, 0.20, 0.30, 0.40],
    "SILVER": [0.10, 0.20, 0.30, 0.40, 0.50],
}
MAINTENANCE_TOP_VOLUME_ML = 0.50

# --- Shelf life by color in days (PRD section 3.5) --------------------------
SHELF_LIFE_DAYS = {
    "GREEN": 30,
    "YELLOW": 90,
    "RED": 180,
    "SILVER": 365,
}

# --- Refill threshold (PRD section 3.5) -------------------------------------
REFILL_THRESHOLD_ML = 1.0

# --- Observation windows in minutes (PRD section 3.6) -----------------------
OBS_STANDARD_MIN = 30
OBS_EXTENDED_MIN = 45

# --- Reaction reduction (PRD section 3.8) -----------------------------------
REDUCTION_PCT = 0.25

# --- Billing (PRD section 3.9) ----------------------------------------------
PRICE_95115_CENTS = 2600
PRICE_95117_CENTS = 3900
PRICE_95165_PER_DOSE_CENTS = 1450
DOSE_CAP = 10

# --- Default clock (PRD section 2.7) ----------------------------------------
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"
