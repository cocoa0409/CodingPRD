"""Domain thresholds — numeric constants from the PRD calculations and rules.

These mirror the values stated in the PRD prose (e.g. the slot length, the
machine wear thresholds, the membership cap, the peak window). Generic
NON_EXISTENT_UUID comes from the framework.
"""

# Slot length: bookings must be a positive whole multiple of this many minutes.
SLOT_MINUTES = 10

# Machine wear thresholds (pitch_count); boundaries are inclusive (>=).
DEGRADE_AT = 5000
OOS_AT = 10000
PITCHES_PER_SESSION = 1000

# Per-model flat machine surcharge, in cents.
MACHINE_SURCHARGE_CENTS = {"WHEEL": 800, "ARM": 1200, "SOFT_TOSS": 300}

# Party pricing components, in cents.
PARTY_BASE_CENTS = 15000
PARTY_PER_GUEST_CENTS = 1200

# Membership-tier discount as a fraction of gross.
TIER_DISCOUNT_PCT = {"NONE": 0.0, "BRONZE": 0.10, "GOLD": 0.25}

# Peak window: minute-of-day [PEAK_START_MIN, PEAK_END_MIN); peak multiplier on lane part.
PEAK_START_MIN = 1020  # 17:00 UTC
PEAK_END_MIN = 1260    # 21:00 UTC
PEAK_MULTIPLIER = 1.5

# Facility posture threshold: posture is CLOSED at this many closed-lane incidents.
CLOSE_THRESHOLD = 2

# Membership minutes and strike limits.
MEMBER_MINUTE_CAP = 1200
MAX_STRIKES = 3
EARLY_CHECKIN_MIN = 30

# Waiver validity window, in days.
WAIVER_VALID_DAYS = 365

# Token refund waterfall.
REFUND_CUTOFF_MIN = 120
REFUND_FORFEIT_PCT = 0.5

# Facility default open hours, minute offsets from midnight UTC.
DEFAULT_OPEN_MINUTE = 480   # 08:00 UTC
DEFAULT_CLOSE_MINUTE = 1320  # 22:00 UTC

# Facility creation defaults.
DEFAULT_TOKEN_PRICE_CENTS = 500
DEFAULT_HOURLY_RATE_CENTS = 4000

# Server startup default logical clock (before any clock is set).
DEFAULT_CLOCK = "2026-04-01T00:00:00Z"

TEST_DEFAULTS = {
    "HOURLY_RATE_CENTS": 4000,
    "TOKEN_PRICE_CENTS": 500,
}
