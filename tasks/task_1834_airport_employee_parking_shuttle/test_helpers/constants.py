"""Domain thresholds and fee constants from the PRD (sections 3.4, 3.7)."""

# Tier base rates and shift multipliers (PRD section 3.4).
BASE_RATE_CORE_CENTS = 12000
BASE_RATE_REMOTE_CENTS = 6000

SHIFT_MULTIPLIER = {
    "DAY": 1.0,
    "NIGHT": 0.75,
    "ROTATING": 0.85,
    "SPLIT": 1.1,
}

SUBSIDY_PCT = {
    "DAY": 0.10,
    "NIGHT": 0.40,
    "ROTATING": 0.25,
    "SPLIT": 0.15,
}

# Violation base fines and escalation (PRD section 3.7).
BASE_FINE_CENTS = {
    "EXPIRED_PERMIT": 5000,
    "WRONG_LOT": 3500,
    "NO_PERMIT_DISPLAY": 2500,
    "BLOCKED_LANE": 7500,
    "PARKED_AFTER_REVOCATION": 10000,
}
ESCALATION_STEP = 0.5
ESCALATION_WINDOW_DAYS = 365

# Tow fee schedule (PRD section 3.7).
TOW_BASE_CENTS = 15000
STORAGE_DAILY_CENTS = 2500

# Program policy defaults (PRD section 3.1).
DEFAULT_PRORATION_MODE = "CALENDAR_DAY"
DEFAULT_SUBSIDY_POOL_CENTS = 0
DEFAULT_OFFER_TTL_HOURS = 72
DEFAULT_VIOLATION_SUSPENSION_THRESHOLD = 3
DEFAULT_TOW_HOLD_HOURS = 48

# Appeal window length (PRD section 3.7).
APPEAL_WINDOW_DAYS = 14

# Notice minimum advance warning (PRD section 3.9).
NOTICE_MIN_ADVANCE_HOURS = 72

# Trip spacing rule (PRD section 3.8).
TRIP_MIN_SPACING_MINUTES = 5

# Startup logical clock (PRD section 2.5).
CLOCK_START = "2026-08-01T00:00:00Z"

# Standard billing period used across fixtures.
AUGUST_PERIOD_START = "2026-08-01"
AUGUST_PERIOD_END = "2026-08-31"
SEPTEMBER_PERIOD_START = "2026-09-01"
SEPTEMBER_PERIOD_END = "2026-09-30"
