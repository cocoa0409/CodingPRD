"""Domain thresholds — numeric constants from the PRD's calculations (§3)."""

THRESHOLDS = {
    # Tier evaluation (PRD §3.1), inclusive thresholds in cents.
    "SILVER_MIN_CENTS": 5_000_000,
    "GOLD_MIN_CENTS": 15_000_000,
    "PLATINUM_MIN_CENTS": 40_000_000,
    # Rebate bands (PRD §3.9).
    "BAND1_LIMIT_CENTS": 10_000_000,
    "BAND2_LIMIT_CENTS": 30_000_000,
    # Color match iteration cap (PRD §3.4).
    "MATCH_MAX_ITERATIONS": 3,
}

RATES = {
    "TAX_RATE_BPS": 825,               # PRD §2.6: 8.25 percent
    "QTY_BREAK_MIN": 10,               # PRD §3.6
    "QTY_BREAK_PCT": 0.03,             # PRD §3.6
    "REBATE_CAP_PCT": 0.05,            # PRD §3.9
    "BAND1_RATE": 0.02,
    "BAND2_RATE": 0.04,
    "BAND3_RATE": 0.06,
    "MISTINT_INITIAL_PCT": 0.50,       # PRD §3.9
    "MISTINT_WEEKLY_DECAY": 0.90,      # PRD §3.9
    "MISTINT_FLOOR_PCT": 0.25,         # PRD §3.9
    "DELIVERY_BUFFER_MINUTES": 30,     # PRD §3.8
}

TIER_DISCOUNT = {"STANDARD": 0.00, "SILVER": 0.05, "GOLD": 0.10, "PLATINUM": 0.15}
TIER_POINT_MULT = {"STANDARD": 1, "SILVER": 2, "GOLD": 3, "PLATINUM": 5}

LOGICAL_CLOCK_DEFAULT = "2026-05-01T00:00:00Z"  # PRD §2.4 startup instant

TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "LIST_PRICE_CENTS": 5_000,
    "VOC_GPL": 100,
    "WINDOW_START": "2026-06-15T09:00:00Z",
    "WINDOW_END": "2026-06-15T10:00:00Z",
}
