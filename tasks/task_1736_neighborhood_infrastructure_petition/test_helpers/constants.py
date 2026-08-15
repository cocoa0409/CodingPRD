"""Domain thresholds — numeric constants from PRD rules."""

THRESHOLDS = {
    # petition support thresholds (pass requires BOTH)
    "PETITION_COUNT_THRESHOLD_PCT": 60.00,
    "PETITION_FRONTAGE_THRESHOLD_PCT": 50.00,
    # protest weight at/above which a supermajority is required
    "SUPERMAJORITY_TRIGGER_PCT": 50.00,
    # council
    "COUNCIL_SEATS": 5,
    "SIMPLE_MAJORITY": 3,
    "SUPERMAJORITY": 4,
    "MAX_REMANDS": 2,
    # hearing statutory notice (days) and objection window length (days)
    "HEARING_NOTICE_DAYS": 10,
    "OBJECTION_WINDOW_DAYS": 15,
    # payment-option election window after levy (days)
    "PAYMENT_OPTION_WINDOW_DAYS": 30,
    # construction scheduling
    "CREW_BUFFER_DAYS": 5,
    "MAX_CONCURRENT_PHASES": 2,
    # delinquency
    "GRACE_DAYS": 30,
    "MONTH_DAYS": 30,
    "PENALTY_MONTHLY_RATE": 0.01,
    # overrun cap: 10% of locked contract price, strictly-greater
    "OVERRUN_CAP_RATIO": 0.10,
    # installment schedule timing
    "DUE_INTERVAL_DAYS": 365,
    "ISSUE_LEAD_DAYS": 30,
    # allocation rate precision (decimal places)
    "RATE_PRECISION_DP": 4,
}

TEST_DEFAULTS = {
    "DEFAULT_INTEREST_RATE_BP": 400,
    "CLOCK_EPOCH": "2026-08-01T00:00:00Z",
    "HEARING_DATE": "2026-08-15T00:00:00Z",
    "HEARING_HELD_AT": "2026-08-15T10:00:00Z",
    "OBJECTION_WINDOW_END": "2026-08-30T00:00:00Z",
    "WINDOW_CLOSE_AT": "2026-08-31T00:00:00Z",
    "PHASE_START": "2026-09-10",
    "PHASE_END": "2026-10-10",
    "PHASE_START_AT": "2026-09-10T09:00:00Z",
    "PHASE_COMPLETE_AT": "2026-10-10T17:00:00Z",
    "TRUE_UP_AT": "2026-10-20T00:00:00Z",
}
