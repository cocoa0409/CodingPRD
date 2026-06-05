"""Domain thresholds — numeric constants from PRD calculations."""

# Luxury tax tier widths and marginal rates (PRD §3.9 / §2.6).
LUXURY_TAX = {
    "TIER_WIDTH": 5_000_000,
    "RATE_TIER_1": 1.5,
    "RATE_TIER_2": 2.0,
    "RATE_TIER_3": 2.5,
}

# Season defaults applied when optional inputs are omitted (PRD §3.1).
SEASON_DEFAULTS = {
    "ROSTER_MIN": 5,
    "ROSTER_MAX": 8,
    "TWO_WAY_MAX": 2,
    "PENALTY_THRESHOLD": 3,
    "LEAGUE_SHARE_PCT": 0.40,
}

# Common test values.
TEST_DEFAULTS = {
    "SALARY_CAP_CENTS": 50_000_000,
    "POOL_CENTS": 10_000_000,
}
