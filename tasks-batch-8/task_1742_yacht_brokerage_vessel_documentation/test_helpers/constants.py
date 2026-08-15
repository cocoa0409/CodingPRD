"""Domain thresholds and calculation constants from the PRD (sections 3.3-3.8)."""

# Logical clock
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Listing desk floor (PRD 3.3): asking price must be at least USD 1,000,000 in cents.
LIST_PRICE_FLOOR_CENTS = 100000000

# Deposit rules (PRD 3.6): earnest money at least 10% (1000 basis points),
# no single DEPOSIT entry above twice the required amount.
DEPOSIT_MIN_PCT_BASIS = 1000
MAX_DEPOSIT_MULTIPLE = 2

# Commission schedule (PRD 3.7), STANDARD tier.
TIER_LOW_MAX_CENTS = 500000000       # below USD 5,000,000 -> 10%
TIER_MID_MAX_CENTS = 2000000000      # below USD 20,000,000 -> 8%; at/above -> 6%
TIER_LOW_RATE = 0.10
TIER_MID_RATE = 0.08
TIER_HIGH_RATE = 0.06
CO_BROKER_SHARE = 0.50
PREMIER_RATE_MULTIPLIER = 1.10
BOUTIQUE_FLAT_RATE = 0.05

# Sales/use tax (PRD 3.7).
STATE_RATES = {
    "FL": 0.06, "CA": 0.0725, "WA": 0.065, "NY": 0.04, "TX": 0.0625,
    "RI": 0.07, "MD": 0.06, "NC": 0.0475, "SC": 0.06, "MA": 0.0625,
    "GA": 0.04, "NJ": 0.06625,
}
STATE_CAP_CENTS = {
    "FL": 1800000,      # USD 18,000
    "SC": 3000000,      # USD 30,000
}

# Prorations (PRD 3.7).
SLIP_FEE_CENTS = 450000              # USD 4,500 per month
FUEL_CREDIT_CENTS = 75000            # USD 750 flat

# Documentation / title fees (PRD 3.7).
COD_FLAT_CENTS = 13300               # USD 133.00
PER_FOOT_CENTS = 400                 # USD 4.00 per foot
STATE_TITLE_RATE = 0.0015
STATE_TITLE_CAP_CENTS = {"CA": 250000, "WA": 225000}
STATE_TITLE_CAP_DEFAULT_CENTS = 200000

# Escrow interest (PRD 3.6).
PROV_RATE = 0.0100
FINAL_RATE = 0.0125
PROV_DAY_BASE = 360
FINAL_DAY_BASE = 365

# Contingency timing (PRD 3.4 / 3.5).
SURVEY_SEA_TRIAL_DEADLINE_DAYS = 10
DOCUMENTATION_DEADLINE_DAYS = 21
CURE_WINDOW_DAYS = 5

# Pagination defaults (PRD 2.3).
PAGE_DEFAULT_LIMIT = 10
PAGE_MAX_LIMIT = 100
