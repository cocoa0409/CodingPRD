"""Domain thresholds and numeric constants (PRD §2.8, §2.9, §3.1, §3.6, §3.7)."""

# Regulatory base caps (birds per minute) by line type (PRD §3.1)
REGULATORY_BASE_CAP_BPM = {"EVISCERATION": 175, "DEBONING": 45}

# Fixed staffing requirements keyed on line type only (PRD §3.1)
REQUIRED_AT_RATED = {
    "EVISCERATION": {"shacklers": 10, "eviscerators": 20, "qa_techs": 2},
    "DEBONING": {"deboners": 12, "qa_techs": 1},
}

# Staffing band boundaries (PRD §3.1)
STAFFING_BAND_FULL = 1.0
STAFFING_BAND_REDUCED = 0.9
REDUCED_BAND_SPEED_FACTOR = 0.9

# Regulatory water limits (PRD §2.8) — strict thresholds; equality compliant
WATER_LIMIT_GAL_PER_1000_BIRDS = 1500.0
WATER_LIMIT_GAL_PER_100LB = 200.0
CHILLER_LIMIT_GAL_PER_1000_BIRDS = 800.0

# Yield / fill constants (PRD §3.4, §3.6, §3.7)
EVISCERATED_BASIS_ALLOWANCE = 0.88
TRIM_ALLOWANCE_PCT = 0.02
POUNDS_PER_LABOR_HOUR = 500.0
FRESH_YIELD_THRESHOLD_PCT = 72.0

# Chill compliance (PRD §3.7)
CHILL_TARGET_TEMP_C = 4.0
CHILL_DEADLINE_HOURS = 8
MIN_CHILL_HOURS = 2
LOT_CHILL_HOURS = 4

# Logical clock startup default (PRD §2.5)
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
