"""Domain thresholds — numeric constants from PRD calculations and rules.

Each constant traces to a verbatim PRD sentence.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "if omitted it defaults to 10, with a minimum of 1 and a maximum
# of 100."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Hold timers — PRD §2.11
# ---------------------------------------------------------------------------
# PRD §2.11: "A HELD TimedEntryReservation auto-expires 15 minutes after
# creation. A HELD CampgroundReservation auto-expires 15 minutes after
# creation. A HELD BackcountryPermit auto-expires 15 minutes after creation."
HELD_MINUTES_DEFAULT: int = 15

# PRD §2.11: "A HELD CampgroundReservation that is created by waitlist
# promotion is held for 4 hours after creation".
# PRD §3.5: "sets that reservation's held_until to 4 hours after the moment
# of promotion (this is the four-hour promotion-hold constant)".
PROMOTION_HOLD_HOURS: int = 4


# ---------------------------------------------------------------------------
# Park config — PRD §2.10, §3.2
# ---------------------------------------------------------------------------
# PRD §2.10: "Each park exposes a timed_entry_window_minutes (default 60),
# which must evenly divide 1440".
DEFAULT_TIMED_ENTRY_WINDOW_MINUTES: int = 60
MINUTES_PER_DAY: int = 1440


# ---------------------------------------------------------------------------
# Booking total — PRD §3.4 booking-total rule
# ---------------------------------------------------------------------------
# PRD §3.4: "Add the fixed booking fee of 800 cents to produce the pre-tax
# subtotal."
BOOKING_FEE_CENTS: int = 800
# PRD §3.4: "Compute the tax amount as the pre-tax subtotal multiplied by
# the tax rate of 0.08".
TAX_RATE: float = 0.08


# ---------------------------------------------------------------------------
# Campground refund — PRD §3.4 tiered-refund rule
# ---------------------------------------------------------------------------
# PRD §3.4: "The fourteen-day constant is 336 hours, the three-day constant
# is 72 hours, and the one-day constant is 24 hours; the half-rate is
# one-half."
CAMPGROUND_REFUND_FOURTEEN_DAY_HOURS: int = 336
CAMPGROUND_REFUND_THREE_DAY_HOURS: int = 72
CAMPGROUND_REFUND_ONE_DAY_HOURS: int = 24
CAMPGROUND_REFUND_HALF_RATE: float = 0.5


# ---------------------------------------------------------------------------
# Timed-entry refund — PRD §3.3 tiered-refund rule
# ---------------------------------------------------------------------------
# PRD §3.3: "When that number is at least 168 (seven days), the refund is
# the full entry_fee_cents. When the number is at least 48 but less than
# 168, the refund is entry_fee_cents multiplied by one-half... When the
# number is less than 48, the refund is zero. The full-window constant for
# this rule is 168 hours, the half-window constant is 48 hours, and the
# half-rate is one-half."
TIMED_ENTRY_FULL_WINDOW_HOURS: int = 168
TIMED_ENTRY_HALF_WINDOW_HOURS: int = 48
TIMED_ENTRY_HALF_RATE: float = 0.5


# ---------------------------------------------------------------------------
# Backcountry refund — PRD §3.7 tiered-refund rule
# ---------------------------------------------------------------------------
# PRD §3.7: "When the number is at least 168 (seven days, the full-window
# constant), the refund is the full fee_cents. When the number is at least
# 24 (one day, the half-window constant) but less than 168, the refund is
# fee_cents multiplied by one-half... When the number is less than 24, the
# refund is zero."
BACKCOUNTRY_REFUND_FULL_WINDOW_HOURS: int = 168
BACKCOUNTRY_REFUND_HALF_WINDOW_HOURS: int = 24
BACKCOUNTRY_REFUND_HALF_RATE: float = 0.5


# ---------------------------------------------------------------------------
# Strike limit — PRD §3.1, §2.12, §3.6
# ---------------------------------------------------------------------------
# PRD §3.1: "Strikes accumulate across the calendar year and may reach 3,
# at which point the visitor is blocked from new lottery applications and
# from new GROUP campground reservations."
# PRD §3.6: "The maximum-strikes constant for filtering is 3."
MAX_LOTTERY_STRIKES: int = 3


# ---------------------------------------------------------------------------
# Timed-entry booking window — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "entry_date_local must be at least the current park-local date
# and at most 30 days ahead; outside that window the request is rejected
# with ERR_OUT_OF_BOOKING_WINDOW."
TIMED_ENTRY_BOOKING_WINDOW_DAYS: int = 30


# ---------------------------------------------------------------------------
# Lottery — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "set each AWARDED application's award_expires_at to 72 hours
# after draw_at."
AWARD_EXPIRY_HOURS: int = 72


# ---------------------------------------------------------------------------
# Timed-entry NO_SHOW window — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "when a CONFIRMED reservation's park-local time has moved past
# window_end_local by more than 60 minutes, the sweep transitions it from
# CONFIRMED to NO_SHOW".
TIMED_ENTRY_NO_SHOW_GRACE_MINUTES: int = 60


# ---------------------------------------------------------------------------
# Site-kind party size — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "1 through 6 inclusive for STANDARD, 7 through 40 inclusive
# for GROUP"
STANDARD_PARTY_MIN: int = 1
STANDARD_PARTY_MAX: int = 6
GROUP_PARTY_MIN: int = 7
GROUP_PARTY_MAX: int = 40

# PRD §3.5: "nights (1 through 14 inclusive)" for WaitlistEntry
WAITLIST_MIN_NIGHTS: int = 1
WAITLIST_MAX_NIGHTS: int = 14

# PRD §3.7: "party_size (1 through 15 inclusive)" for BackcountryPermit
BACKCOUNTRY_PARTY_MIN: int = 1
BACKCOUNTRY_PARTY_MAX: int = 15


# ---------------------------------------------------------------------------
# Test defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "park_name_prefix": "Test Park",
    "park_code_prefix": "TP",
    "park_timezone": "America/Los_Angeles",
    "park_timed_entry_daily_capacity": 50,
    "campground_name_prefix": "Test Camp",
    "campground_standard_count": 5,
    "campground_group_count": 2,
    "nightly_standard_fee_cents": 3500,
    "nightly_group_fee_cents": 12000,
    "zone_name_prefix": "Test Zone",
    "zone_nightly_quota": 20,
    "zone_per_party_fee_cents": 1500,
    "lottery_name_prefix": "Test Lottery",
    "lottery_daily_slot_count": 10,
    "lottery_application_fee_cents": 1000,
    "lottery_permit_fee_cents": 5000,
    "visitor_full_name": "Test Visitor",
    "vehicle_plate": "PLATE01",
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "HELD_MINUTES_DEFAULT",
    "PROMOTION_HOLD_HOURS",
    "DEFAULT_TIMED_ENTRY_WINDOW_MINUTES",
    "MINUTES_PER_DAY",
    "BOOKING_FEE_CENTS",
    "TAX_RATE",
    "CAMPGROUND_REFUND_FOURTEEN_DAY_HOURS",
    "CAMPGROUND_REFUND_THREE_DAY_HOURS",
    "CAMPGROUND_REFUND_ONE_DAY_HOURS",
    "CAMPGROUND_REFUND_HALF_RATE",
    "TIMED_ENTRY_FULL_WINDOW_HOURS",
    "TIMED_ENTRY_HALF_WINDOW_HOURS",
    "TIMED_ENTRY_HALF_RATE",
    "BACKCOUNTRY_REFUND_FULL_WINDOW_HOURS",
    "BACKCOUNTRY_REFUND_HALF_WINDOW_HOURS",
    "BACKCOUNTRY_REFUND_HALF_RATE",
    "MAX_LOTTERY_STRIKES",
    "TIMED_ENTRY_BOOKING_WINDOW_DAYS",
    "AWARD_EXPIRY_HOURS",
    "TIMED_ENTRY_NO_SHOW_GRACE_MINUTES",
    "STANDARD_PARTY_MIN",
    "STANDARD_PARTY_MAX",
    "GROUP_PARTY_MIN",
    "GROUP_PARTY_MAX",
    "WAITLIST_MIN_NIGHTS",
    "WAITLIST_MAX_NIGHTS",
    "BACKCOUNTRY_PARTY_MIN",
    "BACKCOUNTRY_PARTY_MAX",
    "TEST_DEFAULTS",
]
