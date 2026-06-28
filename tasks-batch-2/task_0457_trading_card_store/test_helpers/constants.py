"""Domain thresholds — numeric constants from the PRD's calculations and limits.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Buylist trade-in valuation rates (PRD §3.2)
BUYLIST_RATES = {
    "STORE_CREDIT": 0.70,
    "CASH": 0.50,
}

# Entry-fee loyalty discount in basis points (PRD §3.4)
LOYALTY_DISCOUNT_BPS = {"BRONZE": 0, "SILVER": 500, "GOLD": 1000}
EARLY_BIRD_BPS = 1000
EARLY_BIRD_LEAD_SECONDS = 86400
MAX_DISCOUNT_BPS = 2000

# Pre-order priority scoring (PRD §3.3)
TIER_POINTS = {"BRONZE": 0, "SILVER": 20, "GOLD": 40}
DEPOSIT_STEP_CENTS = 500
DEPOSIT_CAP_PTS = 30
RECENCY_BASE = 25
RECENCY_DECAY = 5

# Grading fee (PRD §3.6)
GRADING_BASE_FEE_CENTS = 1500
VALUE_SURCHARGE_BPS = 100
GRADING_TIER_MULT = {"ECONOMY": 1.0, "STANDARD": 1.5, "EXPRESS": 2.5}

# Loyalty tier thresholds in cents (PRD §3.1)
SILVER_THRESHOLD_CENTS = 50000
GOLD_THRESHOLD_CENTS = 200000

# Venue / rounds limits (PRD §3.5)
STORE_TABLE_COUNT = 8
BUFFER_MINUTES = 30
MAX_ROUNDS = 5

# Server startup default logical clock (PRD §3.8)
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"

# A non-existent but well-formed UUID for not-found tests
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
