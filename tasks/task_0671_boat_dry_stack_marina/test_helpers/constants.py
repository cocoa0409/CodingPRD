"""Domain thresholds — numeric constants from PRD calculations and §2-§3 prose.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Monthly storage base rate by tier (PRD §3.3).
TIER_BASE_CENTS = {"SMALL": 20000, "MEDIUM": 35000, "LARGE": 52500}

# Oversize band & surcharge (PRD §3.3).
OVERSIZE_BAND_FT = 0.5
OVERSIZE_SURCHARGE_PCT = 0.15

# Seasonal multiplier (PRD §3.7).
PEAK_START_MONTH = 5
PEAK_END_MONTH = 9
PEAK_MULTIPLIER = 1.20
OFF_MULTIPLIER = 1.00

# Launch fee composition (PRD §3.5).
LAUNCH_BASE_CENTS = 4500
LAUNCH_PER_FOOT_CENTS = 250
LAUNCH_HEAVY_SURCHARGE_CENTS = 3000
HEAVY_WEIGHT_LBS = 8000
SPLASH_FEE_CENTS = 6000

# Service totals (PRD §3.6).
WINTERIZATION_FEE_CENTS = 25000
HAUL_OUT_FEE_CENTS = 18000
VALET_SPLASH_FEE_CENTS = 6000

# Delinquency threshold (PRD §3.7).
DELINQUENCY_THRESHOLD_CENTS = 50000

# Waitlist priority (PRD §3.4).
DEPOSIT_WEIGHT = 100000

# Marina forklift slot defaults (PRD §2.8).
DEFAULT_FORKLIFT_SERVICE_MINUTES = 30
DEFAULT_FORKLIFT_BUFFER_MINUTES = 15

# A generous liability limit comfortably above any plausible floor (PRD §3.2).
DEFAULT_LIABILITY_LIMIT_CENTS = 50000000
