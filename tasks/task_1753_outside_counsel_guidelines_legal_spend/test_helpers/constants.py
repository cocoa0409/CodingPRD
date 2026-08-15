"""Domain thresholds and defaults — numeric constants from PRD §2.5, §2.7, §3."""

# Logical clock startup default (PRD §2.5).
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Rate-increase sub-cap factors keyed by timekeeper class (PRD §3.4):
# PARTNER gets the full cap, ASSOCIATE 80% of it, PARALEGAL 60% of it.
SUB_CAP_FACTOR = {
    "PARTNER": 1.00,
    "ASSOCIATE": 0.80,
    "PARALEGAL": 0.60,
}

# Scorecard weights (PRD §3.7).
SCORECARD_WEIGHTS = {
    "W_ACK": 0.30,
    "W_REJECTION": 0.30,
    "W_APPEAL": 0.20,
    "W_ACCRUAL": 0.20,
}
SCORECARD_WINDOW_MONTHS = 12

# Block-billing detector: two or more distinct L### markers in the narrative.
MIN_DISTINCT_CODES_FOR_BLOCK = 2

# Standard department policy knobs used across test setups.
DEPT_DEFAULTS = {
    "name": "Test Legal",
    "annual_rate_increase_cap_pct": 5.00,
    "partner_ratio_min_pct": 10,
    "partner_ratio_max_pct": 90,
    "guideline_notice_days": 30,
    "acknowledgment_window_days": 14,
}

# Standard billing values used across test setups.
TEST_DEFAULTS = {
    "FIRM_NAME": "Firm Alpha",
    "MATTER_TITLE": "Test Matter",
    "BUDGET_CENTS": 100_000_000,
    "PARTNER_RATE_CENTS": 100_000,
    "ASSOCIATE_RATE_CENTS": 50_000,
    "EFFECTIVE_YEAR": 2026,
    "PERIOD_START": "2026-08-01T00:00:00Z",
    "PERIOD_END": "2026-09-01T00:00:00Z",
}
