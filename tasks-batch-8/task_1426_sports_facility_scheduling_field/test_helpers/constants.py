"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock (PRD section 2.4): the server default before any test-driving
# call, and the conventional start-of-test instant used by the fixtures.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_START = "2026-08-01T09:00:00Z"

# Slot / prime-time vocabulary (PRD section 2.9).
PRIME_START_MINUTE = 1020          # 5:00 PM local; slots starting at/after are prime
LIGHTS_BUFFER_MINUTES = 30         # required gap between lights windows (inclusive)
LIGHTS_BLOCK_MINUTES = 15          # lights are billed in 15-minute blocks, rounded up

# Application slot duration bounds in minutes (PRD section 3.4).
SLOT_MIN_MINUTES = 30
SLOT_MAX_MINUTES = 480

# Priority scoring constants (PRD section 3.5).
LOYALTY_PER_SEASON = 3
LOYALTY_CAP = 12
STRIKE_PENALTY_POINTS = 12
UTIL_BONUS_HIGH = 10               # utilization >= 80%
UTIL_BONUS_LOW = 5                 # utilization >= 60%

# Standing thresholds (PRD section 3.1).
STRIKE_PROBATION_COUNT = 2         # exactly 2 active strikes -> PROBATION
STRIKE_SUSPENSION_COUNT = 3        # 3 or more active strikes -> SUSPENDED
STRIKE_POINTS_PER_ORDINAL = 10

# Rescheduling (PRD section 3.7).
RAIN_RESCHEDULE_MAX = 2            # hard cap on rain_reschedule_count
RESCHEDULE_HORIZON_DAYS = 10       # new_date <= original permit_date + 10 days

# Refund auto-approval threshold in cents (PRD section 3.8).
REFUND_AUTO_APPROVE_MAX_CENTS = 10000

# Cancellation notice tiers in whole hours / percent (PRD section 3.8).
CANCEL_TIER_FREE_HOURS = 168
CANCEL_TIER_LOW_HOURS = 48
CANCEL_TIER_MID_HOURS = 24
CANCEL_TIER_LOW_PCT = 15
CANCEL_TIER_MID_PCT = 30
CANCEL_TIER_HIGH_PCT = 50
