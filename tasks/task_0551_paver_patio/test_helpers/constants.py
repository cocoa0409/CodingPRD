"""Domain thresholds — numeric constants named in the PRD's calculation rules."""

# Permit determination (PRD §3.3)
PERMIT_WALL_HEIGHT_IN = 48
PERMIT_FLAT_FEE_CENTS = 35000

# Project valuation (PRD §3.3)
TAX_RATE = 0.0725
PROMPT_PAY_THRESHOLD_CENTS = 2_000_000
PROMPT_PAY_RATE = 0.02
WALL_LABOR_RATE_CENTS = 900
FEATURE_LABOR_CENTS = 25000
COMPLEX_SITE_MULTIPLIER = 1.15

# Paver labor tiers (PRD §3.3 step 3)
TIER1_MAX_SQFT = 200
TIER2_MAX_SQFT = 500
TIER1_RATE_CENTS = 700
TIER2_RATE_CENTS = 600
TIER3_RATE_CENTS = 525

# Deposit cap (PRD §3.5)
DEPOSIT_PCT = 0.10
DEPOSIT_FLAT_CAP_CENTS = 100_000

# Retention release + warranty (PRD §3.9)
RETENTION_PCT = 0.05
WARRANTY_TERM_DAYS = 365

# Delivery scheduling (PRD §3.6)
DELIVERY_DAILY_CAP = 2

# Safe deposit amounts (kept comfortably below the cap for the fixtures below)
DEFAULT_DEPOSIT_CENTS = 15000
