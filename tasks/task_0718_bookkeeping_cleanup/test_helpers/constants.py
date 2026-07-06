"""Domain thresholds — numeric constants from PRD calculations."""

# scope_volume_estimate complexity factor in basis points
COMPLEXITY_BP = {"LOW": 10000, "MEDIUM": 11500, "HIGH": 13000}

# fixed_price_quote tiered pricing
TIER1_MAX = 500
TIER2_MAX = 1500
BASE_CENTS = 50000
RATE1_CENTS = 40
RATE2_CENTS = 30

# readiness_score
BLOCKING_PENALTY = 8

# recon_difference tolerance (inclusive boundary)
MATCH_TOLERANCE_CENTS = 100

# Common test defaults for the standard scope fixture (period 2025-01-01..2025-06-30,
# MEDIUM tier, monthly_txn_rate 220): months=6, raw=6*220*11500=15_180_000,
# floor(15_180_000/10000)=1518.
DEFAULT_PERIOD_START = "2025-01-01"
DEFAULT_PERIOD_END = "2025-06-30"
DEFAULT_MONTHLY_TXN_RATE = 220
DEFAULT_ESTIMATED_VOLUME = 1518
