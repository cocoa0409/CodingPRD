"""Domain thresholds — numeric constants from PRD §3 (calculations)."""

THRESHOLDS = {
    # PRD §3.7: tier discount boundaries on committed_qty (inclusive >=)
    "TIER1_MIN_QTY": 500,
    "TIER1_DISCOUNT_PCT": 0.03,
    "TIER2_MIN_QTY": 2000,
    "TIER2_DISCOUNT_PCT": 0.06,
    # PRD §3.4: consumption variance band edges (strictly greater / less)
    "OVER_THRESHOLD_PCT": 0.10,
    # PRD §3.4: rolling window of the 5 most recent usage records
    "WINDOW_SIZE": 5,
    # PRD §3.4: >=3 OVER records within the window flags needs_review
    "TRIGGER_COUNT": 3,
    # PRD §3.9: calendar-month hazard-mass threshold, inclusive
    "HAZARD_MONTH_THRESHOLD_KG": 1000.00,
}

# Logical clock startup default (PRD §2.4)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_DATE = "2026-08-01"

TEST_DEFAULTS = {
    "BASE_PRICE_CENTS": 10000,
    "STANDARD_QTY_PER_PART": 0.0250,
}
