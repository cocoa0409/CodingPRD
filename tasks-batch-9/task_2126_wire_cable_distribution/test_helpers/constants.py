"""Domain thresholds and fixture constants taken from the PRD narrative."""

# ─── Cutting and billing (PRD §3.1, §3.3) ─────────────────────────────────
THRESHOLDS = {
    # A CUT line requests at least 25 feet per conductor (§2.7 item 12);
    # min_cut_length_ft may not be below this absolute safety floor (§3.1).
    "ABSOLUTE_MIN_CUT_FT": 25,
    # Cut-charge tier breakpoints, keyed on per-conductor billable length.
    "SHORT_CUT_TIER_FT": 100,
    "FREE_CUT_TIER_FT": 500,
    "SHORT_CUT_MULTIPLIER": 2,
    "STANDARD_CUT_MULTIPLIER": 1,
    "FREE_CUT_MULTIPLIER": 0,
    "MAX_PARALLEL_SET_SIZE": 4,
    # Freight (§3.4 step two).
    "FREIGHT_BASE_CENTS": 8_500,
    "FREIGHT_PER_PHYSICAL_REEL_CENTS": 2_500,
    # Volume rebate tiers (§3.4 step three).
    "REBATE_TIER_1_BASIS_CENTS": 200_000,
    "REBATE_TIER_2_BASIS_CENTS": 500_000,
    "REBATE_PCT_TIER_0": 0.000,
    "REBATE_PCT_TIER_1": 0.015,
    "REBATE_PCT_TIER_2": 0.030,
    # Free-freight waiver on the post-rebate net (§3.4 step five, inclusive).
    "FREE_FREIGHT_NET_CENTS": 500_000,
    # Segregation of duties (§2.9).
    "SOD_REVIEW_THRESHOLD_CENTS": 250_000,
    # Quote validity (§3.4).
    "QUOTE_VALIDITY_HOURS": 24,
    # Copper index shock tolerance (§3.2), strictly greater than.
    "COPPER_VOLATILITY_TOLERANCE_PCT": 0.03,
    # Cut-floor cleanup buffer in minutes (§3.7).
    "CUT_CLEANUP_BUFFER_MINUTES": 30,
    # Boom-lift threshold in pounds, strictly greater than (§3.8).
    "BOOM_LIFT_WEIGHT_LBS": 250,
    # Deposit return window in elapsed days, inclusive (§3.9).
    "DEPOSIT_RETURN_WINDOW_DAYS": 60,
    "DEPOSIT_RATE_GOOD": 1.00,
    "DEPOSIT_RATE_DAMAGED": 0.50,
    "DEPOSIT_RATE_EXPIRED": 0.00,
}

# ─── Logical clock (PRD §2.5) ─────────────────────────────────────────────
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# A well-formed UUID that is never minted by the service.
UNUSED_UUID = "00000000-0000-4000-8000-000000000000"

# ─── Fixture defaults ─────────────────────────────────────────────────────
TEST_DEFAULTS = {
    "BRANCH_NAME": "Houston DC",
    "REGION_CODE": "TX",
    "CUSTOMER_NAME": "Gulf Electric",
    "CUSTOMER_CREDIT_LIMIT_CENTS": 5_000_000,
    "LOT_CODE": "L1",
    "JOBSITE_ADDRESS": "1200 Bayou Rd",
    "INDEX_EFFECTIVE_DATE": "2026-07-30",
    "INDEX_PRICE_CENTS_PER_LB": 450,
}
