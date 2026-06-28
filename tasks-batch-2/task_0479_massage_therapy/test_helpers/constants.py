"""Domain thresholds — numeric constants from the PRD's pricing and proration rules."""

# No-show / late-cancel fee proration (PRD §3.7).
NO_SHOW_FEE = {
    "FREE_CANCEL_MINUTES": 1440,   # lead >= 1440 -> fraction 0.00
    "LATE_CANCEL_MINUTES": 120,    # lead >= 120 and < 1440 -> fraction 0.50
    "STRIKE_THRESHOLD": 3,         # no_show_strikes >= 3 -> penalized multiplier
    "STRIKE_PENALTY_MULT": 1.50,
}

# Service pricing (PRD §2.6 / §3.8).
MINUTES_PER_HOUR = 60

# Default clock the server boots with (PRD §2.5).
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"

# Allowed appointment durations (PRD §3.4).
ALLOWED_DURATIONS = [30, 60, 90, 120]

# Convenience defaults used across fixtures.
TEST_DEFAULTS = {
    "SWEDISH_BASE_CENTS": 12000,
    "DEEPT_BASE_CENTS": 15000,
}
