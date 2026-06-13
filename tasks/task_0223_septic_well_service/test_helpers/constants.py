"""Domain thresholds — numeric constants from PRD calculations."""

# Work-order tiered cost model (PRD §3.5).
WORK_ORDER_COST = {
    "TRIP_FEE_CENTS": 9000,
    "BASE_INCLUDED_GALLONS": 1000,
    "TIER1_RATE_CENTS": 25,
    "TIER2_RATE_CENTS": 40,
    "EMERGENCY_SURCHARGE_BPS": 5000,
}

# Site risk score weighting (PRD §3.8 / §3.9).
SITE_RISK = {
    "RESULT_WEIGHT": {"PASS": 0, "CONDITIONAL": 30, "FAIL": 60},
    "DEFECT_WEIGHT": 8,
    "DEFECT_CAP": 24,
    "OLD_ASSET_YEARS": 25,
    "AGE_PENALTY": 15,
    "REJECTION_PENALTY": 20,
}

# Compliance temporal gates (PRD §3.4, §3.9).
COOLING_OFF_HOURS = 48
SITE_BUFFER_MINUTES = 120

# Site service defaults (PRD §3.1).
DEFAULT_SERVICE_MINUTES = 60
MIN_SERVICE_MINUTES = 15

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
