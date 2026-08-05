"""Domain thresholds and numeric constants from the PRD."""

# Readiness scoring (§3.3)
READINESS_PASS_THRESHOLD = 12

# Incentive milestone amounts in cents (§3.3, §3.4, §3.5, §3.7)
INCENTIVE_AMOUNTS = {
    "ENROLLMENT": 1000,
    "QUIT_DATE_SET": 1500,
    "SEVEN_DAY_ABSTINENT": 2500,
    "THIRTY_DAY_ABSTINENT": 5000,
    "PROTOCOL_COMPLETE": 2000,
}

# Coaching protocol / NRT (§2.10, §3.2)
PROTOCOL_CALL_TARGET = 4
DEFAULT_SELF_PAY_NRT_COURSES = 2

# Completion bonus (§2.7, §3.8)
COMPLETION_BONUS_RATE = 0.075

# Coaching-call scheduling temporal rules (§2.6)
COACH_BUFFER_MINUTES = 15
SCHEDULE_MIN_LEAD_MINUTES = 60

# Logical clock (§2.6)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# A well-formed UUID that never corresponds to a persisted resource.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
