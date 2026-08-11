"""Domain constants — fee quote bases/multipliers (PRD §3.4), pre-judgment
interest tiers (PRD §3.5), and the logical-clock startup default (PRD §2.5)."""

FEE = {
    "RECIPIENT_BASE_CENTS": 1499,
    "LENDER_SURCHARGE_PCT": 0.15,
    "DELIVERY_BASE_CENTS": 899,
    "METHOD_MULTIPLIER_CERTIFIED_MAIL": 1.0,
    "METHOD_MULTIPLIER_PERSONAL_SERVICE": 2.5,
    "METHOD_MULTIPLIER_EMAIL_STATUTORY": 0.5,
}

INTEREST = {
    "TIER_THRESHOLD_CENTS": 1000000,
    "TIER_BUMP": 0.02,
    "MAX_AWARD_CENTS": 1000000000,
}

CLOCK = {
    # PRD §2.5: "At server start the logical clock reads exactly 2026-05-01T00:00:00Z"
    "STARTUP_DEFAULT": "2026-05-01T00:00:00Z",
}

TEST_DEFAULTS = {
    "SEED_BALANCE_CENTS": 10000000,
    "MODEST_BALANCE_CENTS": 1000000,
}
