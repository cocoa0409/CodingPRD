"""Domain thresholds — numeric constants named in the PRD (§3.4, §3.5, §3.7, §3.8)."""

THRESHOLDS = {
    # Rewash ceiling: a load may be rewashed only while rewash_count < 2 (PRD §3.4).
    "MAX_REWASH_COUNT": 2,
    # COG volume discount tiers (PRD §3.8).
    "COG_TIER1_LBS": 5000,
    "COG_TIER1_PCT": 3,
    "COG_TIER2_LBS": 20000,
    "COG_TIER2_PCT": 7,
    # RENTAL daily rate: 2% of replacement cost per piece-day (PRD §3.8).
    "RENTAL_RATE_PCT": 2,
    # Discrepancy credit: 60% of replacement cost (PRD §3.7).
    "CREDIT_RATE_PCT": 60,
    # Utility surcharge tiered pass-through (PRD §3.8), cents / percent.
    "SURCHARGE_TIER_A_CAP": 100000,
    "SURCHARGE_TIER_A_PCT": 50,
    "SURCHARGE_TIER_B_CAP": 500000,
    "SURCHARGE_TIER_B_PCT": 75,
    "SURCHARGE_TIER_C_PCT": 100,
    # Finish-line buffer on both sides of a run's window (PRD §2.8).
    "LINE_BUFFER_MINUTES": 10,
}

TEST_DEFAULTS = {
    # Default plant policy numbers used by most scenarios.
    "REJECT_RATE_ALERT_PCT": 25.0,
    "PAR_SHORTAGE_ALERT_PIECES": 5,
    "UTILITY_BASELINE_KWH_PER_LB": 1.0,
    "UTILITY_BASELINE_GAL_PER_LB": 2.0,
    # Default TOWEL-like category numbers.
    "PIECE_WEIGHT_LB": 0.5,
    "REPLACEMENT_COST_CENTS": 500,
    "COG_WASH_RATE_CENTS_PER_LB": 120,
    # Generous credit limit so billing tests are not accidentally blocked.
    "CREDIT_LIMIT_CENTS": 100000000,
    # Default billing period: the month of May 2026 (end exclusive).
    "BILLING_PERIOD_START": "2026-05-01",
    "BILLING_PERIOD_END": "2026-06-01",
}
