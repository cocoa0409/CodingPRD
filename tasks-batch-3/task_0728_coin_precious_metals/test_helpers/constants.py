"""Domain thresholds — numeric constants from PRD calculations."""

# 1099-B / ID reporting threshold: $10,000.00 == 1,000,000 integer cents.
REPORTABLE_THRESHOLD_CENTS = 1_000_000

THRESHOLDS = {
    "REPORTABLE_THRESHOLD_CENTS": REPORTABLE_THRESHOLD_CENTS,
}

# Common values reused across setups.
TEST_DEFAULTS = {
    "GOLD_SPOT_CENTS": 200_000,
    "MIN_SELL_SPREAD_PCT": 0.05,
    "BUY_SPREAD_PCT": 0.04,
}
