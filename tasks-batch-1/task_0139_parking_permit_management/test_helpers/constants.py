"""Domain thresholds — numeric constants from the PRD calculations and globals.

Generic NON_EXISTENT_UUID is re-exported from the framework via the barrel.
"""

# Time arithmetic constants (PRD §2.6 / §3.6).
MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 1440

# Permit validity window length (PRD §3.3): valid_until = valid_from + 30 days.
PERMIT_VALID_DAYS = 30

# Fine-escalation tier multipliers (PRD §3.9).
FINE_MULT_T0 = 1.00  # 0 priors
FINE_MULT_T1 = 1.50  # exactly 1 prior
FINE_MULT_T2 = 2.00  # exactly 2 priors
FINE_MULT_T3 = 3.00  # 3+ priors (ceiling)

# Percentage discount base (PRD §3.7).
PERCENT_BASE = 100

# Pagination defaults (PRD §2.3).
PAGINATION = {
    "default_limit": 10,
    "min_limit": 1,
    "max_limit": 100,
    "default_offset": 0,
}

# Common rate-plan defaults used across the design indices.
DEFAULT_RATE_PLAN = {
    "name": "RP",
    "hourly_cents": 500,
    "daily_cap_cents": 4000,
    "monthly_permit_cents": 9000,
    "grace_minutes": 15,
}

# A fixed reference clock used by sessions/permits across the indices.
BASE_CLOCK_UTC = "2026-06-01T10:00:00Z"
