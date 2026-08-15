"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD: the clock starts at exactly this instant).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Bid award gate: review_score must be >= 80 (inclusive boundary).
    "AWARD_MIN_SCORE": 80,
    # Hotel rebate tier floors (pickup ratio, inclusive).
    "TIER_3_FLOOR": 1.0000,
    "TIER_2_FLOOR": 0.9000,
    "TIER_1_FLOOR": 0.8000,
    # Rebate rates per tier.
    "TIER_3_RATE": 0.12,
    "TIER_2_RATE": 0.10,
    "TIER_1_RATE": 0.07,
    # Attrition penalty rate on the shortfall.
    "ATTRITION_RATE": 0.50,
    # Booking cancellation fee rate (rooms_count * rate_cents * 0.5 after cutoff).
    "CANCEL_FEE_RATE": 0.50,
    # Impact direct spend per-capita figure (cents).
    "PER_CAPITA_SPEND_CENTS": 14500,
    # Sanction fee marginal tiers (cents / rates).
    "TIER1_CAP_CENTS": 5_000_000,
    "TIER1_RATE": 0.08,
    "TIER2_CAP_CENTS": 10_000_000,
    "TIER2_RATE": 0.10,
    "TIER3_RATE": 0.12,
    # Official stipend base and certification multipliers (cents).
    "BASE_STIPEND_CENTS": 9999,
    "LEVEL_MULTIPLIER_TRAINEE": 0.6,
    "LEVEL_MULTIPLIER_REGIONAL": 1.0,
    "LEVEL_MULTIPLIER_NATIONAL": 1.5,
    # Officials turnover buffer on each side of a match window (minutes).
    "TURNOVER_BUFFER_MINUTES": 30,
    # Match scheduling lights rule: starts at/after 18:00 need lights.
    "LIGHTS_REQUIRED_HOUR": 18,
    # Minimum roster size.
    "MIN_ROSTER_PLAYERS": 7,
}

TEST_DEFAULTS = {
    # Canonical event window used across test scenarios.
    "EVENT_STARTS_ON": "2026-10-08",
    "EVENT_ENDS_ON": "2026-10-12",
    # Canonical hotel block: 20 rooms/night x 4 nights = 80 contracted room-nights.
    "BLOCK_ROOMS_PER_NIGHT": 20,
    "BLOCK_RATE_CENTS": 15000,
    "BLOCK_START_DATE": "2026-10-08",
    "BLOCK_END_DATE": "2026-10-12",
    "BLOCK_CUTOFF_DATE": "2026-10-01",
    "BLOCK_ATTRITION_ALLOWANCE_PCT": 0.20,
    # Canonical venue and field.
    "VENUE_RENTAL_FEE_CENTS": 200000,
    "VENUE_REVENUE_SHARE_PCT": 0.10,
    "FIELD_SLOT_MINUTES": 90,
    # Canonical division.
    "DIVISION_TEAM_CAP": 4,
    "DIVISION_MIN_TEAMS": 2,
    "DIVISION_REGISTRATION_FEE_CENTS": 10000,
}
