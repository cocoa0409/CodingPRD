"""Domain thresholds and shared test constants from the PRD's calculations."""

# Carcass cut-out yield (PRD section on fabrication/yield accounting)
GRADE_A_MIN_PCT = 72.0
GRADE_B_MIN_PCT = 68.0
MASS_BALANCE_TOLERANCE_LBS = 0.5

# Cold-chain shelf-life dating tiers (deg F thresholds and multipliers)
COLD_CHAIN_LIMIT_F = 40.0
TIER1_MAX_F = 45.0
TIER2_MAX_F = 50.0
TIER1_MULT = 1.0
TIER2_MULT = 1.5
TIER3_MULT = 2.0

# Plant compliance scoring weights
OPEN_ITEM_WEIGHT = 2
MINOR_WEIGHT = 2
MAJOR_WEIGHT = 5

# Recall exercise pass bar and window
RECALL_PASS_THRESHOLD_PCT = 99.5
RECALL_WINDOW_HOURS = 24

# Humane-handling audit thresholds
STUNNING_MIN_PCT = 99.0
SLIPS_MAX_PCT = 3.0
VOCAL_MAX_PCT = 10.0

THRESHOLDS = {
    "GRADE_A_MIN_PCT": GRADE_A_MIN_PCT,
    "GRADE_B_MIN_PCT": GRADE_B_MIN_PCT,
    "MASS_BALANCE_TOLERANCE_LBS": MASS_BALANCE_TOLERANCE_LBS,
    "COLD_CHAIN_LIMIT_F": COLD_CHAIN_LIMIT_F,
    "TIER1_MAX_F": TIER1_MAX_F,
    "TIER2_MAX_F": TIER2_MAX_F,
    "RECALL_PASS_THRESHOLD_PCT": RECALL_PASS_THRESHOLD_PCT,
    "STUNNING_MIN_PCT": STUNNING_MIN_PCT,
    "SLIPS_MAX_PCT": SLIPS_MAX_PCT,
    "VOCAL_MAX_PCT": VOCAL_MAX_PCT,
}

# Logical clock: startup default and the standard production date used by tests.
CLOCK_START_ISO = "2026-08-01T00:00:00Z"
PRODUCTION_DATE = "2026-08-01"
DAY_CLOCK_ISO = "2026-08-01T07:00:00Z"
SHIFT_START_ISO = "2026-08-01T06:00:00Z"
SHIFT_END_ISO = "2026-08-01T18:00:00Z"

# Standard operator identities used across scenarios.
INSPECTOR_1 = "insp-01"
INSPECTOR_2 = "insp-02"
QA_MANAGER_1 = "qa-mgr-1"
QA_MANAGER_2 = "qa-mgr-2"
QA_TECH_1 = "qa-tech-1"
LAB_ANALYST_1 = "lab-1"
PLANT_ADMIN_1 = "plant-admin-1"
PROD_MGR_1 = "prod-mgr-1"

# A well-formed UUID that is guaranteed absent (used for 404 probes).
MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"

TEST_DEFAULTS = {
    "COOLER_CAPACITY_LBS": 10000.0,
    "HOT_CARCASS_WEIGHT_LBS": 1030.0,
    "COLD_CARCASS_WEIGHT_LBS": 1000.0,
    "SHELF_LIFE_DAYS": 10,
}
