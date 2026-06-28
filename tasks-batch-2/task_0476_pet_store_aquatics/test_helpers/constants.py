"""Domain thresholds — numeric constants from PRD calculations (§2.8, §3.3, §3.10, §3.11)."""

# Loyalty tier thresholds (cents). Inclusive lower bounds (§2.8).
SILVER_THRESHOLD = 5_000_000   # $50,000
GOLD_THRESHOLD = 20_000_000    # $200,000

# Loyalty-tier discount fractions read at the relevant calculation time.
TIER_DISCOUNT = {
    "BRONZE": 0.00,
    "SILVER": 0.05,
    "GOLD": 0.10,
}

# Mortality condemnation ratio — inclusive boundary (§3.3).
MORTALITY_CONDEMN_RATE = 0.5

# Loyalty accrual constants.
LOYALTY_POINTS_PER_DOLLAR = 1
SERVICE_MULTIPLIER = {
    "GROOMING": 1,
    "VACCINE": 2,
    "VET_EXAM": 3,
}

# The logical server clock default at startup (§2.11).
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"

THRESHOLDS = {
    "SILVER_THRESHOLD": SILVER_THRESHOLD,
    "GOLD_THRESHOLD": GOLD_THRESHOLD,
    "MORTALITY_CONDEMN_RATE": MORTALITY_CONDEMN_RATE,
    "LOYALTY_POINTS_PER_DOLLAR": LOYALTY_POINTS_PER_DOLLAR,
}
