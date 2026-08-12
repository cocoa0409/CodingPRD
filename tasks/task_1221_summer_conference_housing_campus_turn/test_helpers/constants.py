"""Domain thresholds — numeric constants named in the PRD's calculation rules."""

THRESHOLDS = {
    # Bed-night billing
    "BASE_RATE_CENTS": 4500,
    "TIER_THRESHOLD_BED_NIGHTS": 100,
    "TIER2_RATE_CENTS": 3900,
    "MINOR_SURCHARGE_PCT": 15,
    "WEEKEND_PREMIUM_CENTS": 400,
    "NO_SHOW_FLAT_NIGHTS": 1,
    # Turn windows
    "BASE_TURN_HOURS": 24,
    "DELUXE_TURN_HOURS": 30,
    # Key fees
    "KEY_GRACE_DAYS": 2,
    "KEY_LATE_FEE_PER_DAY_CENTS": 1500,
    "KEY_LATE_FEE_CAP_CENTS": 7500,
    "KEY_LOST_FEE_CENTS": 5000,
    # Damage depreciation
    "MONTHLY_DEPRECIATION_PCT": 2,
    "DEPRECIATION_FLOOR": 0.40,
    "ADMIN_FEE_CENTS": 2500,
    # Revenue waterfall
    "OVERHEAD_PCT": 12,
    "RESERVE_PCT": 8,
    # Cancellation fee tiers
    "FREE_CANCEL_DAYS": 31,
    "REDUCED_CANCEL_DAYS": 15,
    "REDUCED_CANCEL_PCT": 20,
    "LATE_CANCEL_PCT": 50,
    # Linen reconciliation
    "LINEN_PACK_COST_CENTS": 3200,
    "LINEN_DAMAGED_PACK_CENTS": 1600,
    # Dispute window
    "DAMAGE_DISPUTE_WINDOW_DAYS": 7,
}

TEST_DEFAULTS = {
    # The logical clock reads exactly this instant at server startup (PRD).
    "DEFAULT_CLOCK_ISO": "2026-05-01T00:00:00Z",
    "DEFAULT_CLOCK_DATE": "2026-05-01",
    "FALL_OPENING_DATE": "2026-08-20",
    "DEFAULT_CHECKIN_AT": "2026-06-15T15:00:00Z",
    "DEFAULT_CHECKOUT_AT": "2026-06-17T11:00:00Z",
    "DEFAULT_ARRIVAL": "2026-06-15",
    "DEFAULT_DEPARTURE": "2026-06-17",
}

# Non-existent UUID with a valid UUIDv4 shape for 404 probes.
NON_EXISTENT_ID = "00000000-0000-4000-8000-000000000000"
