"""Domain thresholds — numeric constants from PRD calculations."""

# SLA timekeeping defaults (PRD §3.1, §3.4)
SLA_DEFAULTS = {
    "STANDARD_SLA_HOURS": 168,
    "EXPEDITED_SLA_HOURS": 72,
}

# Appeal-window timekeeping (PRD §3.6)
APPEAL_TIER_WINDOW_DAYS = {1: 30, 2: 30, 3: 45}
EXPEDITE_FACTOR = 0.25

# Authorization lifetime (PRD §3.3): approval sets expiry to clock + 365 days.
AUTHORIZATION_VALID_DAYS = 365

# Member cost-share default coinsurance (PRD §3.1)
DEFAULT_COINSURANCE_RATE = 0.2

# Pagination bounds (PRD §2.3)
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "MIN_OFFSET": 0}
