"""Domain thresholds — numeric constants named by the PRD pay, billing,
reliability, and scheduling rules. Generic NON_EXISTENT_UUID comes from the
framework.
"""

# Default logical-clock instant before the clock is ever set.
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00.000Z"

THRESHOLDS = {
    # shift geometry
    "MIN_SHIFT_DURATION_HOURS": 4.0,
    "MAX_SHIFT_DURATION_HOURS": 16.0,
    "MIN_REST_HOURS_BETWEEN_SHIFTS": 8.0,
    "MAX_WEEKLY_SCHEDULED_HOURS": 60.0,
    "MAX_ORDER_HEADCOUNT": 20,
    # claim window / quota
    "SHIFT_CLAIM_LOCK_HOURS": 2.0,
    "MAX_OPEN_CLAIMS_PER_CLINICIAN": 5,
    # credential compliance
    "CREDENTIAL_BUFFER_DAYS": 1,
    # worked-hours / break geometry
    "UNPAID_BREAK_THRESHOLD_MINUTES": 360,
    "UNPAID_BREAK_MINUTES": 30,
    # pay rate, differentials, overtime
    "NIGHT_WINDOW_START_HOUR": 19,
    "NIGHT_WINDOW_END_HOUR": 7,
    "NIGHT_DIFF_CENTS_PER_HOUR": 450,
    "WEEKEND_DIFF_CENTS_PER_HOUR": 300,
    "CRISIS_RATE_MULTIPLIER": 1.25,
    "OVERTIME_THRESHOLD_HOURS": 40.0,
    "OVERTIME_MULTIPLIER": 1.5,
    # timesheet lifecycle
    "TIMESHEET_SUBMISSION_WINDOW_DAYS": 7,
    "TIMESHEET_MAX_DISPUTE_ROUNDS": 2,
    # cancellation / no-show / reliability
    "CANCELLATION_FREE_HOURS": 72.0,
    "CANCELLATION_LATE_HOURS": 24.0,
    "CANCEL_PENALTY_POINTS_LATE": 5,
    "CANCEL_PENALTY_POINTS_VERY_LATE": 15,
    "NO_SHOW_PENALTY_POINTS": 30,
    "SHIFT_COMPLETION_CREDIT_POINTS": 2,
    "FACILITY_CANCELLATION_CREDIT_POINTS": 2,
    "RELIABILITY_BASE_SCORE": 100,
    "RELIABILITY_MIN_SCORE": 0,
    "RELIABILITY_MAX_SCORE": 100,
    "RELIABILITY_WINDOW_DAYS": 90,
    "RELIABILITY_SUSPENSION_THRESHOLD": 60,
    # billing
    "MARKUP_TIER1_MAX_CENTS": 200000,
    "MARKUP_TIER2_MAX_CENTS": 500000,
    "MARKUP_TIER1_MULTIPLIER": 1.45,
    "MARKUP_TIER2_MULTIPLIER": 1.38,
    "MARKUP_TIER3_MULTIPLIER": 1.32,
    "INVOICE_NET_TERMS_DAYS": 30,
    "INVOICE_MAX_PERIOD_DAYS": 31,
}

# Common test rate used across nearly every scenario.
DEFAULT_RN_RATE = 7500
