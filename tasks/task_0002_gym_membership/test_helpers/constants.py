"""Domain thresholds and numeric constants for the gym membership platform.

All values are taken directly from PRD prose; nothing is invented.
"""

# ── Retry & grace (PRD §3.2) ─────────────────────────────────
RETRY_LIMIT = 3
# Late-payment penalty percentage by state_code (PRD §3.2).
LATE_FEE_PCT_BY_STATE = {"CA": 5, "NY": 8, "TX": 3}

# Referral reward cents by invitee plan (PRD §3.1).
REFERRAL_REWARD_CENTS_BY_PLAN = {"BASIC": 1000, "PLUS": 2500, "ELITE": 5000}

# ── Booking pricing (PRD §3.6) ───────────────────────────────
# Class-type base prices in cents.
CLASS_BASE_PRICE_CENTS = {"YOGA": 2000, "SPIN": 2500, "HIIT": 2200}
# Member-tier PT discount percentages.
TIER_PT_DISCOUNT_PCT = {"BASIC": 0, "PLUS": 10, "ELITE": 20}
LATE_BOOKING_SURCHARGE_HOURS = 2
LATE_BOOKING_SURCHARGE_PCT = 25
GROUP_CLASS_MIN_LEAD_MINUTES = 10
TRAINER_BUFFER_MINUTES = 15

# ── No-show (PRD §3.7) ───────────────────────────────────────
NO_SHOW_PENALTY_CENTS = 1000
NO_SHOW_STRIKE_LIMIT = 3
NO_SHOW_WINDOW_DAYS = 30
STRIKE_SUSPENSION_DAYS = 7

# ── Check-in window (PRD §3.7) ───────────────────────────────
CHECK_IN_PRE_WINDOW_MINUTES = 15

# ── Cancellation refund schedules (PRD §3.7) ─────────────────
# Each entry: list of (hours_threshold, refund_pct), strictly descending threshold.
STATE_REFUND_SCHEDULE = {
    "CA": [(24, 100), (2, 50), (0, 0)],
    "NY": [(48, 100), (6, 75), (1, 25), (0, 0)],
    "TX": [(12, 100), (0, 0)],
}

# ── Payment-in-flight window (PRD §3.4) ──────────────────────
PAYMENT_IN_FLIGHT_WINDOW_SECONDS = 120

# ── Pagination (PRD §2.3) ────────────────────────────────────
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# ── Subscription plan base prices ────────────────────────────
# These are convenient TEST defaults — PRD does NOT pin a chain-wide price list,
# it only says "pinned from the chain's plan list at the moment of activation"
# (PRD §3.2). So tests treat the server-pinned base_price_cents as the source
# of truth and use these only to seed factories.
TEST_PLAN_BASE_PRICE_CENTS = {"BASIC": 1999, "PLUS": 4900, "ELITE": 9999}

# ── Confirmation cutoff (PRD §3.5, §3.7) ─────────────────────
# PRD references "the configured confirmation-cutoff window" without pinning a
# number. Tests that exercise the cutoff use the clock to push the present time
# past the boundary; they do NOT assume a specific cutoff in minutes.

THRESHOLDS = {
    "RETRY_LIMIT": RETRY_LIMIT,
    "NO_SHOW_PENALTY_CENTS": NO_SHOW_PENALTY_CENTS,
    "NO_SHOW_STRIKE_LIMIT": NO_SHOW_STRIKE_LIMIT,
    "NO_SHOW_WINDOW_DAYS": NO_SHOW_WINDOW_DAYS,
    "STRIKE_SUSPENSION_DAYS": STRIKE_SUSPENSION_DAYS,
    "GROUP_CLASS_MIN_LEAD_MINUTES": GROUP_CLASS_MIN_LEAD_MINUTES,
    "TRAINER_BUFFER_MINUTES": TRAINER_BUFFER_MINUTES,
    "LATE_BOOKING_SURCHARGE_HOURS": LATE_BOOKING_SURCHARGE_HOURS,
    "LATE_BOOKING_SURCHARGE_PCT": LATE_BOOKING_SURCHARGE_PCT,
    "CHECK_IN_PRE_WINDOW_MINUTES": CHECK_IN_PRE_WINDOW_MINUTES,
}
