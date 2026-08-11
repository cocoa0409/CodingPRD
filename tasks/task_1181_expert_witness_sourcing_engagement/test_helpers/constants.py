"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Daubert eligibility bar: exclusion_count >= 3 barred; == 2 passes
    "MAX_DAUBERT_EXCLUSIONS": 3,
    # Automatic probation: rating_decayed < 3.0 with >= 2 evaluations
    "PROBATION_THRESHOLD": 3.0,
    "MIN_EVALUATIONS": 2,
    # Recency decay: weight = 0.5 ** floor(age_days / 180)
    "DECAY_BASE": 0.5,
    "DECAY_PERIOD_DAYS": 180,
    # Cancellation fee window: strict > (start_at - 72h); fee = 0 at exactly the boundary
    "CANCEL_WINDOW_HOURS": 72,
    "CANCEL_FEE_PCT": 0.50,
    # Venue turnover buffer (closed interval, touching conflicts)
    "TURNOVER_BUFFER_MINUTES": 30,
    # Line-kind multipliers
    "PREP_MULT": 1.00,
    "TESTIMONY_MULT": 1.25,
    "TRAVEL_TIME_MULT": 0.50,
    # Roster / venue defaults
    "DEFAULT_MAX_CONCURRENT": 5,
    "DEFAULT_VENUE_CAPACITY": 20,
}

TEST_DEFAULTS = {
    "HOURLY_RATE_CENTS": 40_000,
    "BUDGET_CENTS": 1_000_000,
    "DEFAULT_CLOCK_ISO": "2026-05-01T00:00:00Z",
    "REPORT_DEADLINE": "2026-07-01T17:00:00Z",
    "TRIAL_DATE": "2026-09-01T00:00:00Z",
}
