"""Domain thresholds and defaults — numeric constants named in PRD prose."""

# PRD §2.4: the logical clock reads exactly this value at startup.
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # PRD §2.10 / §3.9: breach threshold on payment_delinquency_count.
    "BREACH_THRESHOLD": 3,
    # PRD §3.5: late fee accrues at five hundredths of one percent per day.
    "LATE_FEE_DAILY_RATE": 0.0005,
    # PRD §3.6: aggravation multiplier on make-good credit.
    "AGGRAVATION_MULTIPLIER": 1.5,
    # PRD §3.6: shortfall ratio must be strictly greater than this to aggravate.
    "AGGRAVATION_THRESHOLD": 0.20,
    # PRD §3.7: rating shortfall remedy rate.
    "REMEDY_RATE": 0.25,
    # PRD §3.3: escalator must lie between 0.0 and 0.25 inclusive.
    "MAX_ESCALATOR_RATE": 0.25,
}

TEST_DEFAULTS = {
    "SEASON_START": "2026-01-01T00:00:00Z",
    "SEASON_END": "2026-12-31T23:59:59Z",
    "TERM_START": "2026-01-01T00:00:00Z",
    "TERM_END": "2026-12-31T23:59:59Z",
    # Milestone due dates default to after the startup logical clock so that
    # invoicing and on-time payment are reachable without touching the clock.
    "DUE_DATE": "2026-09-01T00:00:00Z",
    "GUARANTEED_RATING_BP": 3000,
}
