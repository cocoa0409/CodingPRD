"""Domain thresholds — numeric constants from PRD calculations."""

# Snow auto-dispatch threshold (PRD §3.4): strictly greater than 2.0 inches.
SNOW_DISPATCH_THRESHOLD_IN = 2.0

# visit_surcharge (PRD §3.6)
SNOW_BASELINE_IN = 2.0
SNOW_RATE_CENTS = 500          # per whole inch over baseline
FERT_ADDON_CENTS = 2500

# skip_credit (PRD §3.7)
SNOW_SKIP_CREDIT_CENTS = 1500
DAYS_IN_BILLING_MONTH = 30
LAWN_SKIP_DAYS = 3

# equipment_wear_score (PRD §3.5)
W_HOURS = 2.0
W_DISPATCH = 5.0
W_AGE = 0.5
MAINTENANCE_THRESHOLD = 100

# route_dispatch_load (PRD §3.5)
OVERTIME_MULT = 1.5
DEPTH_TIER_LOW = 4.0

# final_season_invoice (PRD §3.9)
TAX_PCT = 0.07

# Preference range (PRD §3.1)
GRASS_HEIGHT_MIN_MM = 20
GRASS_HEIGHT_MAX_MM = 120
