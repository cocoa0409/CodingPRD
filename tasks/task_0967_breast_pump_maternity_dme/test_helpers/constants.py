"""Domain thresholds and shared values from the PRD (§2.5, §2.6, §2.7, §3.7)."""

THRESHOLDS = {
    # Bundle discount: tier test compares the pre-discount subtotal against
    # 20000 cents; qualifying garment lines get 10 percent off (PRD §2.6).
    "BUNDLE_THRESHOLD_CENTS": 20000,
    "BUNDLE_DISCOUNT_PCT": 0.10,
    # Warranty replacement budget and reopen budget (PRD §3.7).
    "MAX_WARRANTY_REPLACEMENTS": 2,
    "MAX_REOPENS": 2,
    # Policy defaults (PRD §2.7, §3.1).
    "DEFAULT_PRIOR_AUTH_THRESHOLD_CENTS": 50000,
    "DEFAULT_RESUPPLY_FREQUENCY_DAYS": 90,
    "DEFAULT_PUMP_ALLOWANCE_PER_PERIOD": 1,
}

TEST_DEFAULTS = {
    "PUMP_PRICE_CENTS": 30000,
    "PART_PRICE_CENTS": 500,
    "GARMENT_PRICE_CENTS": 6000,
}

# The logical clock reads exactly this instant at server startup (PRD §2.5).
CLOCK_START = "2026-05-01T00:00:00Z"
