"""Domain thresholds and numeric constants from the PRD business rules."""

# PRD §2.4 — fixed startup default of the logical clock.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# PRD §3.1 — per-incident coverage minimums at certificate verify time.
INSURANCE_MIN_COVERAGE_CENTS = {
    "THEATRE": 100000,
    "FILM": 500000,
    "EVENT": 250000,
    "INDIVIDUAL": 50000,
}

# PRD §3.4 — reservation hold lifetime.
HOLD_HOURS = 72

# PRD §3.3 — days added to closing_date to compute return_by_date.
STRIKE_ALLOWANCE_DAYS = 3

# PRD §3.6 — fixed late-days figure used when a line is reported/auto lost.
LOST_GRACE_DAYS = 7

# PRD §3.5 — category-specific cleaning buffer appended to a line's occupied window.
CLEANING_BUFFER_DAYS = {
    "COSTUME": 2,
    "PROP": 1,
    "SET_DRESSING": 1,
    "WEAPONRY": 3,
    "ACCESSORY": 1,
}

# PRD §3.5 — condition multiplier applied to per-unit rental charges at assignment.
RENTAL_CONDITION_MULTIPLIER = {"A": 1.20, "B": 1.00, "C": 0.85}

# PRD §3.7 — valuation grade multiplier for damage claims.
VALUATION_GRADE_MULTIPLIER = {"A": 1.00, "B": 0.80, "C": 0.60, "D": 0.40}

# PRD §3.6 — base cleaning fee per item category.
CLEANING_BASE_FEE_CENTS = {
    "COSTUME": 1500,
    "PROP": 800,
    "SET_DRESSING": 1200,
    "WEAPONRY": 2500,
    "ACCESSORY": 500,
}

# PRD §3.6 — rush multiplier fires when queue depth at ticket creation is >= threshold.
BACKLOG_THRESHOLD = 10
RUSH_MULTIPLIER = 1.5

# PRD §3.7 — depreciation parameters for DEPRECIATED_REPLACEMENT valuation.
USEFUL_LIFE_YEARS = 5
SALVAGE_FLOOR_PCT = 0.10

# Standard rate card used by most scenarios: long-run at 8 weeks (0.20),
# deep-run at 16 weeks (0.30), late fee 0.10 of the daily rate per late day.
DEFAULT_RATE_CARD = {
    "name": "RC-2026",
    "long_run_threshold_weeks": 8,
    "long_run_discount_pct": 0.20,
    "deep_run_threshold_weeks": 16,
    "deep_run_discount_pct": 0.30,
    "late_fee_daily_pct": 0.10,
}

# Standard catalog item: Victorian tailcoat, COSTUME, replacement 100000,
# daily 1000, weekly 5000.
DEFAULT_ITEM = {
    "name": "Victorian tailcoat",
    "period": "VICTORIAN",
    "category": "COSTUME",
    "size_class": "M",
    "alteration_policy": "TAILORING_ALLOWED",
    "replacement_value_cents": 100000,
    "base_daily_rate_cents": 1000,
    "base_weekly_rate_cents": 5000,
}

# Standard production dates: rehearsal 2026-08-10, opening 2026-09-01.
DEFAULT_REHEARSAL_START = "2026-08-10"
DEFAULT_PERFORMANCE_START = "2026-09-01"
SHORT_RUN_CLOSING = "2026-09-20"     # 20 days -> run_weeks 2 (never long-run at threshold 8)
LONG_RUN_CLOSING = "2026-10-26"      # 56 days -> run_weeks 8 (long-run at threshold 8)
DEEP_RUN_CLOSING = "2026-12-21"      # 112 days -> run_weeks 16 (deep tier at threshold 16)
