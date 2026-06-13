"""Domain thresholds — numeric constants from PRD calculations and rules."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # re-exported for tests

# A syntactically valid UUID that resolves to no entity. Used for not-found /
# bad-reference probes.
NON_EXISTENT_UUID = NON_EXISTENT_UUID

# Repeat-offender escalation (§3.5)
ROLLING_WINDOW_DAYS = 365
REPEAT_THRESHOLD = 2          # prior_violation_count >= 2 -> REPEAT
CHRONIC_THRESHOLD = 4         # prior_violation_count >= 4 -> CHRONIC
ESCALATION_MULTIPLIER = {
    "FIRST": 1.0,
    "REPEAT": 1.5,
    "CHRONIC": 2.0,
}

# Lien administrative-fee tier (§3.12)
ADMIN_TIER_CENTS = 500000     # principal >= 500000 -> 0.10, else 0.05
ADMIN_RATE_LOW = 0.05
ADMIN_RATE_HIGH = 0.10
FORECLOSURE_WAIT_DAYS = 90

# Hearing / contest windows (§3.8)
GRACE_CONTEST_DAYS = 3
HEARING_BUFFER_DAYS = 7
MAX_CONTINUANCES = 2

# Standard fee-schedule rows used by the worked chains.
FEE_SCHEDULES = {
    "MINOR": {
        "violation_class": "MINOR",
        "base_fine_cents": 5000,
        "daily_accrual_cents": 200,
        "max_total_cents": 50000,
        "cure_days": 21,
    },
    "MAJOR": {
        "violation_class": "MAJOR",
        "base_fine_cents": 20000,
        "daily_accrual_cents": 500,
        "max_total_cents": 100000,
        "cure_days": 14,
    },
    "HAZARD": {
        "violation_class": "HAZARD",
        "base_fine_cents": 50000,
        "daily_accrual_cents": 1000,
        "max_total_cents": 300000,
        "cure_days": 7,
    },
}
