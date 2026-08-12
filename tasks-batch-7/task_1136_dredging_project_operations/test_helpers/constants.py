"""Domain thresholds — numeric constants from PRD §2.4, §3.3, §3.8, §3.9."""

DEFAULT_LOGICAL_NOW = "2026-05-01T00:00:00Z"  # startup clock (PRD §2.4)

THRESHOLDS = {
    # Production estimate (PRD §3.3)
    "WEATHER_ALLOWANCE_PCT": 0.20,
    "DEPTH_FACTOR_SHALLOW_MAX_FT": 30.0,  # below 30 -> factor 1.00
    "DEPTH_FACTOR_MID_MAX_FT": 50.0,  # 30..<50 -> 0.85; >= 50 -> 0.70
    # Standby claims (PRD §3.8)
    "STANDBY_DEDUCTIBLE_HOURS": 4.0,
    # Reconciliation (PRD §3.9)
    "RECON_TOLERANCE_PCT": 15.0,
    # Quantity payment waterfall (PRD §3.9)
    "TIER1_PCT": 0.8,
    "TIER2_RATE": 0.90,
    "TIER3_RATE": 0.75,
}

MATERIAL_FACTOR = {
    "SAND": 1.00,
    "SILT": 0.85,
    "CLAY": 0.70,
    "GRAVEL": 0.55,
    "ROCK": 0.35,
}

STANDBY_REASON_MULTIPLIER = {
    "WEATHER": 1.0,
    "OWNER_DIRECTED": 1.0,
    "SPECIES_SHUTDOWN": 0.5,
    "EQUIPMENT_BREAKDOWN": 0.0,
}

TEST_DEFAULTS = {
    "BASE_RATE_CENTS_PER_CY": 1500,
    "STANDBY_RATE_CENTS_PER_HOUR": 5000,
    "LD_CENTS_PER_DAY": 100000,
    "RATED_DAILY_PRODUCTION_CY": 4000,
    "DESIGN_QUANTITY_CY": 40000,
}
