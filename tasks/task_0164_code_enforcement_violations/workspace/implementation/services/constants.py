"""System constants (SCAFFOLD §1.3 calculations.constants)."""

# Repeat-offender rolling window and thresholds.
ROLLING_WINDOW_DAYS = 365
REPEAT_THRESHOLD = 2
CHRONIC_THRESHOLD = 4

# Contest / hearing temporal rules.
GRACE_CONTEST_DAYS = 3
HEARING_BUFFER_DAYS = 7
MAX_CONTINUANCES = 2

# Lien admin-fee tier and foreclosure wait.
ADMIN_TIER_CENTS = 500000
FORECLOSURE_WAIT_DAYS = 90

# Escalation multipliers per repeat tier.
TIER_MULTIPLIER = {"FIRST": 1.0, "REPEAT": 1.5, "CHRONIC": 2.0}
