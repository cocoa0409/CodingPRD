"""Domain thresholds and defaults from the PRD's pricing/work-rule narratives."""

THRESHOLDS = {
    # PRD: "the period's `paid_break_minutes` when the spread reaches ten hours
    # (600 minutes) or more, and zero below that line."
    "SPREAD_BREAK_THRESHOLD_MINUTES": 600,
    # PRD: "`daily_ot_threshold_minutes` ... defaulting to 480 (eight hours) when omitted"
    "DEFAULT_DAILY_OT_THRESHOLD_MINUTES": 480,
    # PRD: "`weekly_ot_threshold_minutes` ... defaulting to 2400 (forty hours) when omitted"
    "DEFAULT_WEEKLY_OT_THRESHOLD_MINUTES": 2400,
    # PRD: "no more than 960 — sixteen hours"
    "MAX_ACTUAL_PLATFORM_MINUTES": 960,
    # PRD: "the operator's `vacation_hours_balance` must cover a full forty-hour vacation week"
    "VACATION_WEEK_HOURS": 40,
}

PRICING = {
    # PRD: "The base pay rate is fifty cents per paid minute; minutes classified
    # as overtime are paid at one and a half times that base rate."
    "BASE_RATE_CENTS_PER_MIN": 50,
    "OT_MULTIPLIER": 1.5,
}

TEST_DEFAULTS = {
    "EFFECTIVE_START_DATE": "2026-09-01",
    "EFFECTIVE_END_DATE": "2026-11-30",
    "SPREAD_LIMIT_MINUTES": 780,
    "PAID_BREAK_MINUTES": 30,
    "EXTRA_BOARD_RATIO_PCT": 20,
}
