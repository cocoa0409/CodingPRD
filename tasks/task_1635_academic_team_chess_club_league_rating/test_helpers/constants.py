"""Domain thresholds — numeric constants from the PRD (§2.5, §3.5, §3.7, §3.9)."""

THRESHOLDS = {
    # Rating formula (PRD §3.5)
    "RATING_FLOOR": 100,
    "RATING_CEILING": 2900,
    "PROVISIONAL_SWING": 400,
    "K_LOW": 32,
    "K_MID": 24,
    "K_HIGH": 16,
    "K_TIER_BOUND_1": 2100,
    "K_TIER_BOUND_2": 2400,
    # Travel stipend cap (PRD §3.9)
    "MEET_CAP": 10,
    # Season invoice volume-credit tiers (PRD §3.9)
    "TIER1_CENTS": 40000,
    "TIER2_CENTS": 80000,
    "TIER1_PCT": 0.05,
    "TIER2_PCT": 0.10,
    # Qualification bids (PRD §3.9)
    "MIN_BID_POINTS": 6,
    "BID_OFFER_DAYS": 7,
    # Withdrawal half-refund tier (PRD §3.7)
    "CLOSED_REFUND_PCT": 0.5,
}

TEST_DEFAULTS = {
    # Default logical-clock reading before any call (PRD §2.5)
    "CLOCK_START": "2026-08-01T00:00:00Z",
    "SEASON_START": "2026-08-01",
    "SEASON_END": "2027-05-31",
    "DUES_DEADLINE": "2026-09-01T00:00:00Z",
    "REGULAR_DUE_CENTS": 2500,
    "LATE_DUE_CENTS": 3750,
    "TRAVEL_BASE_CENTS": 1500,
    "MEET_DATE": "2026-09-05",
    "TOURNAMENT_START": "2026-10-02",
    "TOURNAMENT_END": "2026-10-03",
}
