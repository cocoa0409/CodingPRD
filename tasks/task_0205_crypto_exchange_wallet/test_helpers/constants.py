"""Domain thresholds — numeric constants from the PRD's calculations and tables."""

# PRD §3.6: travel-rule threshold of 3,000 USD.
TRAVEL_RULE_THRESHOLD_USD = 3000

# PRD §3.5 / §3.11: time windows.
WITHDRAWAL_ADDRESS_HOLD_HOURS = 24
STAKING_UNBOND_COOLDOWN_DAYS = 7
VOLUME_WINDOW_DAYS = 30

# PRD §3.8: MARKET BUY slippage ceiling (five-percent), and the worst-case taker fee fraction.
MARKET_SLIPPAGE_CEILING = 0.05
WORST_CASE_TAKER_FEE_BPS = 30  # thirty basis points, used for reserve headroom

# PRD §3.7: per-tier daily withdrawal USD ceiling.
KYC_TIER_DAILY_CEILING_USD = {
    "TIER_0": 0,
    "TIER_1": 1000,
    "TIER_2": 50000,
    "TIER_3": 1000000,
}

# PRD §3.11: a year is 365 days for reward accrual.
YEAR_SECONDS = 31536000
BPS_DENOMINATOR = 10000

# Pagination (PRD §2.3).
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_LIMIT = 1

# Common test fixtures default values.
TEST_DEFAULTS = {
    "BTC_SPOT": 40000,
    "ETH_SPOT": 2000,
    "USD_SPOT": 1,
}
