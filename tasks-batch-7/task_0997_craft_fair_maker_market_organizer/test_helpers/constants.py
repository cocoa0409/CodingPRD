"""Domain thresholds and shared instants — numeric constants from the PRD."""

# Logical clock instants (PRD §2.5: startup clock reads exactly 2026-05-01T00:00:00Z)
CLOCK_START = "2026-05-01T00:00:00Z"
WINDOW_START = "2026-05-01T00:00:00Z"
WINDOW_END = "2026-05-10T00:00:00Z"
EVENT_OPENS = "2026-06-01T09:00:00Z"
EVENT_CLOSES = "2026-06-01T18:00:00Z"
AFTER_CLOSE = "2026-06-02T00:00:00Z"

# Booth fee tier multipliers and category uplifts (PRD §3.3)
TIER_MULTIPLIER = {"STANDARD": 1.00, "CORNER": 1.25, "ANCHOR": 1.60}
CATEGORY_UPLIFT_PCT = {"FOOD": 0.10, "MIXED": 0.05}

# Commission tiering (PRD §3.7: first 100,000 cents at base pct, +2 points above)
COMMISSION_TIER_THRESHOLD_CENTS = 100_000
COMMISSION_TIER_BUMP = 0.02

# Booth constraints (PRD §3.1, §3.5)
ANCHOR_MIN_FOOTPRINT_SQM = 20
PAYMENT_WINDOW_HOURS = 72

# Rounding trace audit strings (PRD §2.7)
TRACE_PER_LINE_THEN_SUM = "per_line_then_sum"
TRACE_SUM_THEN_ROUND = "sum_then_round"

TEST_DEFAULTS = {
    "VENUE_CAPACITY": 100,
    "JURY_QUORUM": 2,
    "COMMISSION_PCT_STANDARD": 0.10,
    "COMMISSION_PCT_ANCHOR": 0.05,
    "BOOTH_PRICE_CENTS": 5000,
    "CATEGORY_CAP": 3,
}
