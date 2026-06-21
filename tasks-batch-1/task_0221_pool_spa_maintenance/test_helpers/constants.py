"""Domain thresholds — numeric constants from the PRD calculations (§2.7, §3.5, §3.9)."""

# Dosing recommendation constants (PRD §3.5)
FC_TARGET = {"CHLORINE": 3.0, "SALTWATER": 3.0, "BROMINE_SPA": 4.0}
TA_TARGET = 100.0  # total-alkalinity target ppm, all water types
DOSE_PER_PPM_PER_10K = {"CHLORINE": 14.0, "SALTWATER": 20.0, "BROMINE_SPA": 11.0}
ALK_DOSE_PER_PPM_PER_10K = 1.5
PH_PENALTY = 1.25
PH_PENALTY_THRESHOLD = 7.8  # penalty fires strictly above this

# Per-visit billing constants (PRD §3.5)
RECOVERY_SURCHARGE_CENTS = 4500
GREEN_TIER1_CENTS = 12000   # volume <= 15000
GREEN_TIER2_CENTS = 18000   # 15000 < volume <= 30000
GREEN_TIER3_CENTS = 26000   # volume > 30000
GREEN_TIER1_MAX_GALLONS = 15000
GREEN_TIER2_MAX_GALLONS = 30000

# Repair total constants (PRD §3.9)
LABOR_RATE_PER_HOUR_CENTS = 9000
SEVERITY_MULT = {"MINOR": 1.0, "MAJOR": 1.15, "CRITICAL": 1.35}
TAX_RATE = 0.07

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
