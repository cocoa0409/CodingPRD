"""Configured business constants.

Constants pinned by the scaffold/PRD are taken verbatim. The per-decision-class
base prices / base labor hours and the per-machine-type market / replacement
bases are referenced by the PRD as "configured" tables without pinned values;
the values below are the server configuration used consistently everywhere.
"""

# --- Wear index (calculations.wear_index) ---
PD_REF = 20.0
SR_REF = 10.0
BL_REF = 15.0
W_PD = "0.5"
W_SR = "0.3"
W_BL = "0.2"
WEAR_CLAMP = "1.5"

# --- Recommended path thresholds (calculations.recommended_path) ---
FULL_THRESHOLD = "80.00"
MECH_THRESHOLD = "40.00"

# --- Quote (calculations.quote_price_cents) ---
LABOR_RATE_CENTS = 14500
TIER1_MIN = 50000000
TIER2_MIN = 100000000
TIER1_RATE = "0.02"
TIER2_RATE = "0.05"

# Configured per-decision-class base price (cents) and base labor hours.
BASE_PRICE_CENTS = {
    "RETROFIT_ONLY": 7500000,
    "MECHANICAL_REBUILD": 18000000,
    "FULL_REBUILD": 32000000,
}
BASE_HOURS = {
    "RETROFIT_ONLY": 120,
    "MECHANICAL_REBUILD": 320,
    "FULL_REBUILD": 560,
}

# --- Residual valuation (calculations.residual_value_cents) ---
DEPRECIATION = "0.12"
SCRAP_FLOOR = 2000000
# Configured per-machine-type market base (cents) and replacement cost (cents).
MARKET_BASE_CENTS = {
    "LATHE": 12000000,
    "MILL": 15000000,
    "GRINDER": 20000000,
}
REPLACEMENT_COST_CENTS = {
    "LATHE": 30000000,
    "MILL": 38000000,
    "GRINDER": 45000000,
}

# --- Acceptance evaluation (calculations.acceptance_evaluation) ---
TOL_POS = "20.0"
TOL_REP = "10.0"
N_SAMPLES = 5

# --- Warranty drift (calculations.warranty_drift_evaluation) ---
DRIFT_TOL = "15.0"

# --- Warranty months per decision class (calculations.warranty_end) ---
WARRANTY_MONTHS = {
    "RETROFIT_ONLY": 6,
    "MECHANICAL_REBUILD": 12,
    "FULL_REBUILD": 24,
}

# --- Training sessions per decision class (calculations.sessions_required) ---
SESSIONS_REQUIRED = {
    "RETROFIT_ONLY": 1,
    "MECHANICAL_REBUILD": 2,
    "FULL_REBUILD": 3,
}

# --- Obsolescence multiplier on part lines ---
OBS_MULTIPLIER_OBSOLETE = "1.8"
OBS_MULTIPLIER_NORMAL = "1.0"

# --- Rework surcharges (calculations.rework_surcharge) ---
FAIL_RATE = "0.05"
ESCALATION_RATE = "0.10"

# --- Shipment stage sibling gap (calculations.shipment_stage_tiling) ---
MIN_GAP_DAYS = 2

# --- Trade-in offer lifetime (days) ---
OFFER_EXPIRY_DAYS = 30
