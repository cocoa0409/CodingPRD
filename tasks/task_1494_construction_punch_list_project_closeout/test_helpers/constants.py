"""Domain thresholds — numeric constants from PRD §2.6, §3.2, §3.4, §3.5, §3.6, §3.7."""

# Logical clock initial reading (PRD §2.4).
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# Project creation bounds (PRD §3.1).
MIN_CONTRACT_VALUE_CENTS = 1000
MAX_RETAINAGE_PCT = 0.25

# Retainage release math (PRD §3.6).
REDUCTION_PCT = 0.5
MINOR_WITHHOLD_CENTS = 25000

# Substantial-completion gates (PRD §3.4).
MINOR_OPEN_ALLOWANCE = 5

# Warranty window (PRD §3.7).
WARRANTY_PERIOD_DAYS = 365
SLA_DAYS = {"CRITICAL": 1, "MAJOR": 7, "MINOR": 30}

# Scheduling rules (PRD §3.2, §3.5).
MIN_WALK_DURATION_MINUTES = 30
ROOM_TURNOVER_BUFFER_MINUTES = 30
MAX_RESCHEDULE_COUNT = 2

TEST_DEFAULTS = {
    "CONTRACT_VALUE_CENTS": 10_000_000,
    "RETAINAGE_PCT": 0.10,
    # round_half_up(10_000_000 * 0.10)
    "EXPECTED_HELD_CENTS": 1_000_000,
}
