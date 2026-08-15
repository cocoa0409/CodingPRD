"""Domain thresholds — numeric constants named in PRD §2.6, §3.1, §3.3–§3.6."""

THRESHOLDS = {
    # Meal window: a meal is timely when its MEAL_OUT occurs no more than
    # 360 minutes after check-in / the previous MEAL_IN (PRD §3.6).
    "MEAL_WINDOW_MINUTES": 360,
    # meal_penalty_count caps at 3 violations (PRD §3.6).
    "MEAL_PENALTY_CAP": 3,
    # The daily rate buys an eight-hour day (PRD §3.6).
    "REGULAR_MINUTES": 480,
    "HOURS_PER_DAY_RATE": 8,
    # Union OT tiers: first tier capped at 120, second tier beyond 600 (PRD §3.6).
    "UNION_OT1_CAP_MINUTES": 120,
    "UNION_OT2_FLOOR_MINUTES": 600,
    # Non-union OT tiers: first tier capped at 240, second beyond 720 (PRD §3.6).
    "NONUNION_OT1_CAP_MINUTES": 240,
    "NONUNION_OT2_FLOOR_MINUTES": 720,
    # Estimate assumes exactly one timely thirty-minute meal (PRD §3.6).
    "ASSUMED_MEAL_MINUTES": 30,
    # Turnaround: at least 600 minutes of rest between booking windows (PRD §3.3).
    "TURNAROUND_MINUTES": 600,
    # No-show grace: at least sixty minutes past call_time (PRD §3.4).
    "NO_SHOW_GRACE_MINUTES": 60,
    # Replacement case deadline: call_time plus 120 minutes (PRD §3.4/§3.5).
    "REPLACEMENT_DEADLINE_MINUTES": 120,
    # Reliability: 100 minus twenty points per lifetime no-show (PRD §3.1).
    "NO_SHOW_PENALTY": 20,
    "NO_SHOW_SUSPEND_THRESHOLD": 3,
    # Compliance index: -15 per noncompliant wrap; publish gate at 30 (PRD §2.6).
    "NONCOMPLIANT_WRAP_PENALTY": 15,
    "PUBLISH_GATE_MINIMUM": 30,
}

TEST_DEFAULTS = {
    "SHOOT_DATE": "2026-08-10",
    "GENERAL_CALL_TIME": "2026-08-10T07:00:00Z",
    "PRE_SHOOT_CLOCK": "2026-08-10T06:55:00Z",
    "SCHEDULED_DURATION_MINUTES": 600,
    "UNION_RATE_CENTS": 10000,
    "NONUNION_RATE_CENTS": 10000,
    "LOCATION": "Lot 1",
    "TITLE": "Film",
    "STUDIO_CODE": "STX",
    "PAYROLL_COMPANY_NAME": "EntPay",
    "PERIOD_LABEL": "2026-W33",
}

# A well-formed UUID that matches nothing (empty database).
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"
