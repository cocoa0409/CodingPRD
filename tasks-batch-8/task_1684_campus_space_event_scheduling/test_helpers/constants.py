"""Domain thresholds and numeric constants stated in the PRD."""

THRESHOLDS = {
    # PRD section 2.4 — logical clock start
    "CLOCK_START": "2026-08-01T00:00:00Z",
    # PRD section 3.1 — standing thresholds (no-show strikes)
    "PROBATION_STRIKES": 2,
    "SUSPENSION_STRIKES": 3,
    # PRD section 3.4 — deadlines and windows
    "DECISION_DEADLINE_HOURS": 72,
    "CONFIRM_DEADLINE_HOURS": 48,
    "CHECKIN_EARLY_MINUTES": 30,
    "CHECKIN_LATE_MINUTES": 15,
    # PRD section 3.4 — cancellation fee tiers
    "CANCEL_FREE_NOTICE_HOURS": 72,
    "CANCEL_HALF_NOTICE_HOURS": 24,
    "CANCEL_HALF_BPS": 5000,
    "CANCEL_FULL_BPS": 10000,
    # PRD section 3.4 — bump shield
    "BUMP_SHIELD_HOURS": 72,
    # PRD section 3.4/3.6 — no-show flat fee
    "NO_SHOW_FEE_CENTS": 5000,
    # PRD section 3.6 — insurance
    "MIN_LIABILITY_COVERAGE_CENTS": 100000000,
    "INSURANCE_SURCHARGE_BPS": 200,
    # PRD section 3.7 — deposits and forfeits
    "KEY_DEPOSIT_CENTS": 7500,
    "CARD_DEPOSIT_CENTS": 2500,
    "LATE_RETURN_FORFEIT_BPS": 5000,
    "RETURN_DEADLINE_HOURS": 24,
    # PRD section 3.3 — academic priority scoring
    "ENROLLMENT_WEIGHT": 10,
    "LARGE_CLASS_BONUS": 100,
    "LARGE_CLASS_THRESHOLD": 100,
    # PRD section 3.2 — room defaults
    "DEFAULT_TURNAROUND_BUFFER_MINUTES": 30,
    "DEFAULT_PEAK_MULTIPLIER_BPS": 12500,
    # PRD section 3.4 — event duration bounds
    "MIN_EVENT_DURATION_MINUTES": 30,
    "MAX_EVENT_DURATION_MINUTES": 480,
    # PRD section 3.5 — service window margin
    "SERVICE_WINDOW_MARGIN_HOURS": 2,
    # PRD section 2.3 — pagination
    "DEFAULT_PAGE_LIMIT": 10,
    "MAX_PAGE_LIMIT": 100,
}

# PRD section 3.3 — per-feature priority weights
FEATURE_WEIGHTS = {
    "PIANO": 50,
    "STAGE": 40,
    "LAB_BENCHES": 30,
    "KITCHEN_ACCESS": 25,
    "VIDEO_CONF": 20,
    "SOUND_SYSTEM": 15,
    "PROJECTOR": 10,
    "ADA_LIFT": 5,
}

# PRD section 3.1 — precedence tier stamped from org_type
PRECEDENCE_TIERS = {
    "INTERNAL_DEPARTMENT": 200,
    "STUDENT_GROUP": 100,
    "EXTERNAL": 50,
}

TEST_DEFAULTS = {
    "INTERNAL_RATE": 5000,
    "STUDENT_RATE": 2500,
    "EXTERNAL_RATE": 12000,
    "LOW_RATE": 1000,
}
