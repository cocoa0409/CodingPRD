"""Constants pinned by the PRD / scaffold."""

# Plan price list (cents) — pinned at subscription activation
PLAN_PRICE_CENTS = {
    "MONTHLY": {
        "BASIC": 2000,   # $20/mo
        "PLUS": 4000,    # $40/mo
        "ELITE": 8000,   # $80/mo
    },
    "ANNUAL": {
        "BASIC": 20000,
        "PLUS": 40000,
        "ELITE": 80000,
    },
}

# Tier ordering for minimum-tier comparison
TIER_RANK = {"BASIC": 0, "PLUS": 1, "ELITE": 2}

# Personal training discount by tier (percent)
TIER_PT_DISCOUNT_PCT = {"BASIC": 0, "PLUS": 10, "ELITE": 20}

# Class type base price (cents)
CLASS_BASE_PRICE_CENTS = {"YOGA": 2000, "SPIN": 2500, "HIIT": 2200}

# Late-booking surcharge
LATE_BOOKING_SURCHARGE_HOURS = 2
LATE_BOOKING_SURCHARGE_PCT = 25

# Minimum lead time (minutes) for group-class bookings
MIN_LEAD_MINUTES = 10

# Confirmation cutoff (minutes) before class starts_at
CONFIRM_CUTOFF_MINUTES = 30

# Trainer buffer (minutes) — closed-on-both-sides PT envelope
TRAINER_BUFFER_MINUTES = 15

# Check-in window relative to ClassSession.starts_at / ends_at
CHECK_IN_PREWINDOW_MINUTES = 15  # inclusive [starts_at-15min, ends_at]

# No-show
NO_SHOW_PENALTY_CENTS = 1000
NO_SHOW_WINDOW_DAYS = 30
NO_SHOW_STRIKE_LIMIT = 3
STRIKE_SUSPENSION_DAYS = 7

# Payment-attempt retry limit per period
RETRY_LIMIT = 3

# Cancellation: "non-terminal payment attempt in last 2 minutes" guard
PAYMENT_IN_FLIGHT_SECONDS = 120

# Late-fee percent by state
LATE_FEE_PCT_BY_STATE = {"CA": 5, "NY": 8, "TX": 3}
DEFAULT_LATE_FEE_PCT = 5

# Grace period day count by state
GRACE_PERIOD_DAYS_BY_STATE = {"CA": 7, "NY": 10, "TX": 5}
DEFAULT_GRACE_PERIOD_DAYS = 7

# Max voluntary suspension days by state
MAX_SUSPENSION_DAYS_BY_STATE = {"CA": 90, "NY": 60, "TX": 120}
DEFAULT_MAX_SUSPENSION_DAYS = 90

# Refund schedules by state (list of {hours_threshold, refund_pct}, sorted highest threshold first)
STATE_REFUND_SCHEDULE = {
    "CA": [
        {"hours_threshold": 24, "refund_pct": 100},
        {"hours_threshold": 2, "refund_pct": 50},
        {"hours_threshold": 0, "refund_pct": 0},
    ],
    "NY": [
        {"hours_threshold": 48, "refund_pct": 100},
        {"hours_threshold": 6, "refund_pct": 75},
        {"hours_threshold": 1, "refund_pct": 25},
        {"hours_threshold": 0, "refund_pct": 0},
    ],
    "TX": [
        {"hours_threshold": 12, "refund_pct": 100},
        {"hours_threshold": 0, "refund_pct": 0},
    ],
}
DEFAULT_REFUND_SCHEDULE = [
    {"hours_threshold": 24, "refund_pct": 100},
    {"hours_threshold": 0, "refund_pct": 0},
]

# Admin/cascade refund — always 100%
ADMIN_REFUND_PCT = 100

# Referral reward (cents) by invitee's subscribed plan
REFERRAL_REWARD_CENTS_BY_PLAN = {"BASIC": 1000, "PLUS": 2500, "ELITE": 5000}


def grace_period_days(state_code):
    return GRACE_PERIOD_DAYS_BY_STATE.get(state_code, DEFAULT_GRACE_PERIOD_DAYS)


def late_fee_pct(state_code):
    return LATE_FEE_PCT_BY_STATE.get(state_code, DEFAULT_LATE_FEE_PCT)


def max_suspension_days(state_code):
    return MAX_SUSPENSION_DAYS_BY_STATE.get(state_code, DEFAULT_MAX_SUSPENSION_DAYS)


def refund_schedule(state_code):
    return STATE_REFUND_SCHEDULE.get(state_code, DEFAULT_REFUND_SCHEDULE)
