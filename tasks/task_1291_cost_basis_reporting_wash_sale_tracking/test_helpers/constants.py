"""Domain thresholds — numeric constants from PRD calculations (§2.7–§2.9, §3)."""

THRESHOLDS = {
    # PRD §3.1: regulatory defaults stamped on a new firm.
    "TAX_YEAR_OPEN": 2025,
    "WASH_SALE_WINDOW_DAYS": 30,
    "CORRECTION_DEADLINE_DAYS": 1095,
    # PRD §3.3: long-term requires strictly more than 365 holding days.
    "LONG_TERM_THRESHOLD_DAYS": 365,
}

# PRD §2.9: the logical clock starts fixed at this instant and never uses wall-clock time.
DEFAULT_STARTUP_CLOCK = "2026-08-01T00:00:00Z"

# A clock reading past filed_at(=2026-08-01) + 1095 days (deadline 2029-08-01).
PAST_CORRECTION_DEADLINE_CLOCK = "2029-08-02T00:00:00Z"

TEST_DEFAULTS = {
    "COVERED_EFFECTIVE_DATE": "2011-01-01T00:00:00Z",
    "LOT_ACQ_DATE": "2025-01-05T00:00:00Z",
    "TRADE_DATE": "2025-06-10T00:00:00Z",
    "SETTLEMENT_DATE": "2025-06-11T00:00:00Z",
}
