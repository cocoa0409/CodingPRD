"""Domain thresholds — numeric constants from PRD §3 calculation rules."""

# Renal dose adjustment (PRD §3.4): CrCl tier edges and factors.
RENAL_TIER_FULL_MIN = 50.0   # crcl >= 50 -> factor 1.00
RENAL_TIER_MID_MIN = 30.0    # 30 <= crcl < 50 -> 0.75
RENAL_TIER_LOW_MIN = 10.0    # 10 <= crcl < 30 -> 0.50; below 10 -> 0.25
RENAL_FACTOR_FULL = 1.00
RENAL_FACTOR_MID = 0.75
RENAL_FACTOR_LOW = 0.50
RENAL_FACTOR_MIN = 0.25
OBESITY_BMI = 30.0

# Dose-rounding step ladder (PRD §3.4).
STEP_SMALL = 0.1   # raw < 1
STEP_MID = 0.5     # 1 <= raw <= 10
STEP_LARGE = 1.0   # raw > 10
BAND_MID_MIN = 1.0
BAND_LARGE_MIN = 10.0

# Beyond-use dating table, hours, keyed [usp_risk_level][storage_condition] (PRD §3.5).
BUD_TABLE_HOURS = {
    "LOW": {"ROOM": 48, "REFRIGERATED": 336, "FROZEN": 1080},
    "MEDIUM": {"ROOM": 30, "REFRIGERATED": 216, "FROZEN": 1080},
    "HIGH": {"ROOM": 24, "REFRIGERATED": 72, "FROZEN": 1080},
}
MAX_EXTENSION_HOURS = 720

# Batch yield size tiers and waste tolerances (PRD §3.5).
TIER_SMALL_MAX_ML = 25.0    # total < 25 -> SMALL
TIER_MEDIUM_MAX_ML = 100.0  # 25 <= total <= 100 -> MEDIUM; > 100 -> LARGE
TOL_SMALL_PCT = 60.0
TOL_MEDIUM_PCT = 30.0
TOL_LARGE_PCT = 10.0
MAX_REWORK = 2

# ADC discrepancy thresholds (PRD §3.6).
DISCREPANCY_THRESHOLD_CII = 2
DISCREPANCY_THRESHOLD_OTHER = 5

# Diversion risk score (PRD §3.7).
RISK_WINDOW_DAYS = 30
RISK_VARIANCE_DIVISOR = 2
RISK_W_VARIANCE = 10
RISK_W_WASTE = 5
RISK_W_AFTER_HOURS = 3
RISK_C_II_MULTIPLIER = 1.5
RISK_HARD_VARIANCE_TRIGGER = 10
RISK_ESCALATION_FLOOR = 80
RISK_OPEN_CASE_THRESHOLD = 75
RISK_WATCH_THRESHOLD = 50
RISK_AFTER_HOURS_START = 22  # hour >= 22
RISK_AFTER_HOURS_END = 6     # hour < 6

# Logical clock default (PRD §2.6).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Default session window covering the default clock (used by fixtures).
DEFAULT_SESSION_START = "2026-08-01T00:00:00Z"
DEFAULT_SESSION_END = "2026-08-03T00:00:00Z"

# Standard healthy-patient fixture (CrCl well above 50 -> renal factor 1.00).
HEALTHY_PATIENT = {
    "full_name": "Healthy Pat",
    "date_of_birth": "1996-08-01T00:00:00Z",
    "sex": "M",
    "height_cm": 180.0,
    "weight_kg": 80.0,
    "scr_mg_dl": 0.9,
}

# Default drug fixture: non-controlled, 10 mg/mL, 10 mL vials.
DEFAULT_DRUG = {
    "schedule": "NON_CONTROLLED",
    "concentration_mg_per_ml": 10.0,
    "vial_size_ml": 10.0,
}
