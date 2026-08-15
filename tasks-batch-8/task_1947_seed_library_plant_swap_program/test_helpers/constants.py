"""Domain thresholds — numeric constants named in PRD §2 and §3."""

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # PRD §3.3: PASS requires result_pct of at least 70.00.
    "VIABILITY_PASS_PCT": 70.00,
    # PRD §3.4: lifetime ceiling of two hundred packets per lot.
    "LOT_MAX_PACKETS": 200,
    # PRD §3.5: due_at is exactly twenty-one days after checked_out_at.
    "LOAN_DAYS": 21,
    # PRD §3.5: exactly three overdue checkouts suspends, two does not.
    "OVERDUE_SUSPENSION_THRESHOLD": 3,
    # PRD §3.5: ninety-day half-life for the decay-weighted score.
    "DECAY_HALF_LIFE_DAYS": 90,
    # PRD §3.5: tier boundaries and limits.
    "TIER_TRUSTED_MIN_TERMINALS": 5,
    "TIER_TRUSTED_RATE": 0.90,
    "TIER_PROBATION_MIN_TERMINALS": 3,
    "TIER_PROBATION_RATE": 0.60,
    "LIMIT_PROBATION": 2,
    "LIMIT_STANDARD": 5,
    "LIMIT_TRUSTED": 8,
}

CREDIT_VALUATION = {
    # PRD §3.6: base value per item type.
    "BASE_SEED_PACKET": 2,
    "BASE_PLANT_START": 5,
    "BASE_CUTTING": 3,
    # PRD §3.6: condition multipliers.
    "CONDITION_MULT_EXCELLENT": 1.5,
    "CONDITION_MULT_GOOD": 1.0,
    "CONDITION_MULT_FAIR": 0.5,
    # PRD §3.6: flat 2-credit bonus for a rare variety.
    "RARITY_BONUS": 2,
    # PRD §3.6: per-member per-event credit cap.
    "MAX_CREDITS_PER_MEMBER_EVENT": 25,
}

TEST_DEFAULTS = {
    "ZONE": "ZONE_5A",
    "ZONE_ALT": "ZONE_7A",
    "HARVEST_YEAR": 2026,
}
