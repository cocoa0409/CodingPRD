"""Domain thresholds and time-gated windows from the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework. Values here mirror the
fixed numeric constants the PRD names in §2.5 / §3.5 / §3.8 / §3.9 and the
shared fixture conventions used throughout the test suite.
"""

# Time-gated windows (PRD §3.5, §3.8, §3.9, §2.5).
NO_SHOW_GRACE_MINUTES = 15        # §3.5: fifteen-minute no-show grace
NOTIFY_TTL_MINUTES = 10           # §3.8: ten-minute waitlist offer window
WAITLIST_EXPIRY_MINUTES = 120     # §3.8: 120-minute waitlist expiry
HOLD_EXPIRY_DAYS = 7              # §3.9: seven-day hold authorization window

# Cancellation-fee tier (PRD §3.5).
LATE_TIER_HOURS = 2               # at/above 2h out → 50% tier
LATE_TIER_PCT = 0.50

# Restaurant policy defaults (PRD §3.1).
DEFAULT_TURN_TIME_MINUTES = 90
DEFAULT_CLEANUP_BUFFER_MINUTES = 15
DEFAULT_LATE_CANCEL_CUTOFF_HOURS = 24
DEFAULT_NO_SHOW_STRIKE_BLOCK_THRESHOLD = 3
DEFAULT_PER_SEAT_DEPOSIT_CENTS = 2500
DEFAULT_DEPOSIT_REQUIRED_PARTY_THRESHOLD = 6

# ServicePeriod defaults (PRD §2.5, §3.1).
DEFAULT_SLOT_INTERVAL_MINUTES = 30

# Private-dining defaults (PRD §3.4).
DEFAULT_DEPOSIT_PCT = 0.25
DEFAULT_SERVICE_CHARGE_PCT = 0.0

# Pagination bounds (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

THRESHOLDS = {
    "NO_SHOW_GRACE_MINUTES": NO_SHOW_GRACE_MINUTES,
    "NOTIFY_TTL_MINUTES": NOTIFY_TTL_MINUTES,
    "WAITLIST_EXPIRY_MINUTES": WAITLIST_EXPIRY_MINUTES,
    "HOLD_EXPIRY_DAYS": HOLD_EXPIRY_DAYS,
    "LATE_TIER_HOURS": LATE_TIER_HOURS,
    "LATE_TIER_PCT": LATE_TIER_PCT,
}
