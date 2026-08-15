"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Leak grading (PRD §3.5)
G1_LEL_THRESHOLD_PCT = 25.0
G1_MIGRATION_BUILDING_FT = 20.0
G2_PPM_THRESHOLD = 10000.0
G2_BUILDING_FT = 50.0
G2_LEL_THRESHOLD_PCT = 5.0
G1_REPAIR_DAYS = 1
G2_REPAIR_DAYS = 30
G3_REPAIR_DAYS = 365
MAX_REGRADE_COUNT = 3

# Instrument calibration (PRD §2.6)
MAX_DRIFT_PCT = 5.0
CALIBRATION_INTERVAL_DAYS = {
    "FLAME_IONIZATION": 90,
    "CGI": 60,
    "OMD": 90,
    "AERIAL_LIDAR": 180,
    "CP_VOLTMETER": 365,
}

# CP anomaly threshold (PRD §3.10)
CP_ANOMALY_THRESHOLD_MV = -850.0

# Survey run acceptance (PRD §3.4)
MIN_COVERAGE_PCT = 95.0

# Re-survey interval bases in days (PRD §3.9)
RESURVEY_BASE_DAYS = {
    ("TRANSMISSION", True): 90,
    ("TRANSMISSION", False): 180,
    ("DISTRIBUTION", True): 180,
    ("DISTRIBUTION", False): 365,
    ("SERVICE", True): 365,
    ("SERVICE", False): 730,
}
G1_RESURVEY_FACTOR = 0.25
G2_RESURVEY_FACTOR = 0.5
CP_ANOMALY_FACTOR = 0.5

# Risk score weights (PRD §3.8)
W_AGE = 0.20
W_MATERIAL = 0.15
W_LEAK = 0.30
W_CP = 0.20
HCA_MULTIPLIER = 1.5
HIGH_RISK_THRESHOLD = 70.0
MATERIAL_SCORE_MAP = {
    "STEEL": 0.8,
    "CAST_IRON": 1.0,
    "PLASTIC_PE": 0.2,
    "PLASTIC_PVC": 0.3,
    "COPPER": 0.5,
}

# Crew dispatch selector (PRD §3.6)
UTILIZATION_WEIGHT = 0.7
REGION_MATCH_WEIGHT = 0.3

# Report filing deadline (PRD §3.11)
REPORT_FILING_DEADLINE_DAYS = 60

# Return-to-service lookback (PRD §3.12)
CLEAN_CP_LOOKBACK_DAYS = 90

# Logical clock default (PRD §2.4)
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
