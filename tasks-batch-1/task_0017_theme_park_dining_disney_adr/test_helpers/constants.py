"""Domain constants — numeric thresholds and tiered-pricing tables from PRD §3.

All monetary amounts are integer cents. Multipliers are decimals stored verbatim
(PRD §3.5).
"""

# ─── No-show fee tiered pricing (PRD §3.5) ────────────────────────────────

CHARACTER_SURCHARGE_PER_SEAT_CENTS = 1000
REPEAT_OFFENDER_THRESHOLD = 1   # strike_after == 1 → tier1 multiplier 1.0
REPEAT_OFFENDER_MAX = 3         # strike_after 2..3 → tier2 multiplier 1.075; 4+ → tier3
REPEAT_OFFENDER_MULTIPLIER_TIER1 = 1.0
REPEAT_OFFENDER_MULTIPLIER_TIER2 = 1.075
REPEAT_OFFENDER_MULTIPLIER_TIER3 = 1.250


# ─── Lightning Lane pricing (PRD §3.7) ────────────────────────────────────

LL_BASE_CENTS = {
    "SINGLE_PASS": 1500,
    "MULTI_PASS": 2500,
}

LL_PARK_MULT = {
    "MAGIC_KINGDOM": 1.175,
    "EPCOT": 1.075,
    "ANIMAL_KINGDOM": 1.000,
    "HOLLYWOOD_STUDIOS": 1.100,
}

LL_CHARACTER_UPLIFT_CENTS = 500
LL_REDEMPTION_WINDOW_MINUTES_AFTER_SLOT_END = 60


# ─── Booking window arithmetic (PRD §3.3) ─────────────────────────────────

BOOKING_WINDOW_LEAD_DAYS = 60
DAILY_OPEN_LOCAL_HHMM = "06:00"
RESORT_TZ = "America/New_York"


# ─── Reservation lifecycle thresholds (PRD §3.4, §3.5) ────────────────────

FREE_CANCEL_WINDOW_HOURS_BEFORE_SLOT = 2
CHECK_IN_GRACE_MINUTES_BEFORE_SLOT = 15
NO_SHOW_STRIKE_SUSPEND_THRESHOLD = 5    # PRD §3.1: "no_show_strike_count >= 5"


# ─── Pagination defaults (PRD §2.3) ───────────────────────────────────────

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ─── Allowed allergen codes (PRD §3.6) ────────────────────────────────────

ALLOWED_ALLERGEN_CODES = (
    "PEANUT", "TREE_NUT", "GLUTEN", "DAIRY", "EGG", "SHELLFISH", "SOY",
)


# ─── Allowed park codes (PRD §3.1) ────────────────────────────────────────

ALLOWED_PARK_CODES = (
    "MAGIC_KINGDOM", "EPCOT", "ANIMAL_KINGDOM", "HOLLYWOOD_STUDIOS",
)


# ─── Test defaults ────────────────────────────────────────────────────────

TEST_DEFAULTS = {
    "RESTAURANT_NAME": "Test Restaurant",
    "GUEST_FULL_NAME": "Test Guest",
    "OPENING_LOCAL_TIME": "11:00",
    "CLOSING_LOCAL_TIME": "22:00",
}
