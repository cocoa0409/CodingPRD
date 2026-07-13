"""Domain thresholds — numeric constants from the PRD's fee, risk, and validity rules."""

# --- Certificate fee (PRD §3.7) ---------------------------------------------
BASE_FEE_BY_CLASS = {
    "POWER_BOILER": 20000,
    "HEATING_BOILER": 10000,
    "PRESSURE_VESSEL": 15000,
}
# MAWP pressure-tier fee thresholds (psig):
#   p <= 15 -> 0 ; 15 < p <= 150 -> 4500 ; 150 < p <= 600 -> 12000 ; p > 600 -> 25000
MAWP_TIER_FEE = {
    "LOW_LE_15": 0,
    "MEDIUM_LE_150": 4500,
    "HIGH_LE_600": 12000,
    "EXTREME_GT_600": 25000,
}
DEFICIENCY_SURCHARGE_PER = 2500
INCIDENT_SPECIAL_SURCHARGE = 30000
DEFAULT_ADMIN_FEE_PCT = 0.075

# --- Vessel risk score (PRD §3.9) -------------------------------------------
BASE_BY_CLASS = {
    "POWER_BOILER": 30,
    "HEATING_BOILER": 15,
    "PRESSURE_VESSEL": 20,
}
CRIT_WEIGHT = 8
NONCRIT_WEIGHT = 3
INCIDENT_PENALTY_PER = 25
SUSPENDED_PENALTY = 40
CLEAN_BONUS = 10

# --- Certificate validity window (PRD §3.7) ---------------------------------
INTERVAL_BY_CLASS = {
    "POWER_BOILER": 12,
    "HEATING_BOILER": 12,
    "PRESSURE_VESSEL": 24,
}

# --- Pagination (PRD §2.3) --------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- Logical clock startup default (PRD §2.5) -------------------------------
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"
