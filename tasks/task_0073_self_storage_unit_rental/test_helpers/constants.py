"""Domain thresholds — numeric constants from the PRD billing/lien calculations."""

# Facility default dunning/pricing parameters (PRD §3.1).
FACILITY_DEFAULTS = {
    "CLIMATE_PREMIUM_PCT": 0.20,
    "LIEN_DEFAULT_DAYS": 90,
    "LATE_FEE_GRACE_DAYS": 5,
    "LATE_FEE_CENTS": 2000,
}

# Fixed lien administration cost folded into redemption and the surplus waterfall (PRD §3.9).
LIEN_ADMIN_COST_CENTS = 15000

# Statutory windows (PRD §3.8) measured in days.
NOTICE_PERIOD_DAYS = 14
COOLING_OFF_DAYS = 14
PRE_LIEN_DAYS = 30  # DELINQUENT -> PRE_LIEN threshold (PRD §3.5)

# Insurance tier lookups (PRD §3.7).
TIER_PREMIUM_CENTS = {"BASIC": 1000, "STANDARD": 1500, "PREMIUM": 2500}
TIER_LIMIT_CENTS = {"BASIC": 200000, "STANDARD": 500000, "PREMIUM": 1500000}
