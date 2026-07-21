"""Domain thresholds — numeric constants from PRD calculations (§2.5, §2.9, §3.3, §3.8)."""

# Trade discount cap and tier percentages (PRD §2.9, §3.3).
DISCOUNT_CAP_CENTS = 200000
STANDARD_PCT = 0.00
SILVER_PCT = 0.08
GOLD_PCT = 0.15

# Tier thresholds; comparisons are inclusive >= (PRD §2.9).
GOLD_THRESHOLD_CENTS = 5000000
SILVER_THRESHOLD_CENTS = 2000000

# Restocking / grace (PRD §3.8).
RESTOCK_FEE_PCT = 0.20
RESTOCK_GRACE_DAYS = 14

# Logical clock default at server startup (PRD §3.10).
DEFAULT_CLOCK_ISO = "2026-07-01T00:00:00Z"

TEST_DEFAULTS = {
    "BASE_PRICE_CENTS": 5000,
    "BASE_WATTAGE": 40,
    "CREDIT_LIMIT_CENTS": 100000000,
}
