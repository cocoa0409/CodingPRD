"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Trustee fee tiers (PRD §3.6)
    "TIER1_CAP_CENTS": 100_000_000,        # one million dollars
    "TIER2_CAP_CENTS": 300_000_000,        # three million dollars
    "TIER1_RATE": "0.01",
    "TIER2_RATE": "0.0075",
    "TIER3_RATE": "0.005",
    "MIN_QUARTERLY_FEE_CENTS": 125_000,    # twelve hundred fifty dollars
    "INCOME_SPLIT_RATE": "0.5",
    # Receipt allocation shares (PRD §3.5)
    "RENTAL_INCOME_SHARE": "0.90",
    "MINERAL_INCOME_SHARE": "0.10",
    # Committee quorum (PRD §3.3)
    "QUORUM": 3,
    # Share class invariant (PRD §2.5)
    "FULL_CLASS_BPS": 10_000,
    # Concentration limit (PRD §3.4): strictly greater than 25% is rejected
    "CONCENTRATION_PCT": 25,
    # Complex-trust exemption (PRD §3.8)
    "EXEMPTION_CENTS": 30_000,
    # Objection window (PRD §2.9): 30 days, inclusive of the thirtieth day
    "OBJECTION_WINDOW_DAYS": 30,
}

TEST_DEFAULTS = {
    "FUNDING_CENTS": 200_000_000,          # 2,000,000.00
    "Q3_PERIOD_START": "2026-07-01",
    "Q3_PERIOD_END": "2026-09-30",
    "Q4_PERIOD_START": "2026-10-01",
    "Q4_PERIOD_END": "2026-12-31",
    "INITIAL_CLOCK": "2026-08-01T00:00:00Z",
}
