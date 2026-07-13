"""Domain thresholds and defaults from the PRD's pricing, capacity, and timing rules."""

# Dynamic pricing tiers (PRD Section 3.3).
THRESHOLDS = {
    "TIER1_PCT": 50,          # >= 50% sold enters the 1.25 multiplier tier
    "TIER2_PCT": 80,          # >= 80% sold enters the 1.50 multiplier tier
    "TIER1_MULT": 1.25,
    "TIER2_MULT": 1.50,
    "PLATINUM_FLOOR_MULT": 2.00,
    "CEIL_MULT": 3,           # face value clamp ceiling = 3 x base
    "MAX_SEATS_PER_HOLD": 2,  # per-hold seat cap
}

# Default logical clock at server startup (PRD Section 2.5).
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "BASE_FACE_VALUE_CENTS": 9990,
    "SERVICE_FEE_PCT": 0.15,
    "SERVICE_FEE_FLAT_CENTS": 500,
    "HOLD_TTL_MINUTES": 15,
    "PURCHASE_WINDOW_MINUTES": 30,
    "EVENT_DATETIME": "2026-08-01T19:00:00Z",
    "PROMOTER_ID": "prm_1",
}
