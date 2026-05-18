"""Domain thresholds — numeric constants from PRD §3 calculations.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Signup-bonus calculation — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "the qualifying total is at least three thousand dollars
# (three hundred thousand cents) — the comparison is at-or-greater-than,
# so exactly three thousand dollars triggers but two thousand nine hundred
# ninety-nine dollars and ninety-nine cents does not".
SIGNUP_MIN_SPEND_CENTS: int = 300_000

# PRD §2.12: "signup_bonus_deadline_at is precisely 90 days after
# opened_at".
SIGNUP_WINDOW_DAYS: int = 90

# PRD §3.1: "Awarding deposits sixty thousand points to the ledger as a
# single SIGNUP_BONUS entry whose delta_points is positive sixty
# thousand".
SIGNUP_BONUS_POINTS: int = 60_000


# ---------------------------------------------------------------------------
# Earn-rate fallbacks — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "the category rate falls back to the platform fallback of
# one hundred basis points (one percent)".
BASE_BPS: int = 100


# ---------------------------------------------------------------------------
# Tier thresholds & multipliers — PRD §3.5 / §3.4
# ---------------------------------------------------------------------------
# PRD §3.5: "The transition from STANDARD to GOLD fires when the post
# brings the counter to at-or-above six hundred thousand cents (six
# thousand dollars)".
TIER_GOLD_THRESHOLD_CENTS: int = 600_000

# PRD §3.5: "The transition from GOLD to PLATINUM fires when the post
# brings the counter to at-or-above one million five hundred thousand
# cents (fifteen thousand dollars)".
TIER_PLATINUM_THRESHOLD_CENTS: int = 1_500_000

# PRD §3.4: "STANDARD yields ten thousand (one-times multiplier), GOLD
# yields twelve thousand five hundred (one-and-a-quarter times), and
# PLATINUM yields fifteen thousand (one-and-a-half times)".
TIER_STANDARD_MULT_BPS: int = 10_000
TIER_GOLD_MULT_BPS: int = 12_500
TIER_PLATINUM_MULT_BPS: int = 15_000


# ---------------------------------------------------------------------------
# Statement-credit redemption — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "POINTS_FIRST requires requested_points to be at-or-above
# two thousand five hundred points, AMOUNT_FIRST requires
# requested_amount_cents to be at-or-above two thousand five hundred
# cents (twenty-five dollars)".
MIN_REDEMPTION_POINTS: int = 2_500
MIN_REDEMPTION_CENTS: int = 2_500

# PRD §3.6: "STANDARD requires one hundred points per dollar (one cent
# per point); GOLD requires ninety points per dollar; PLATINUM requires
# eighty points per dollar".
POINTS_PER_DOLLAR_STANDARD: int = 100
POINTS_PER_DOLLAR_GOLD: int = 90
POINTS_PER_DOLLAR_PLATINUM: int = 80

POINTS_PER_DOLLAR_BY_TIER: dict = {
    "STANDARD": POINTS_PER_DOLLAR_STANDARD,
    "GOLD": POINTS_PER_DOLLAR_GOLD,
    "PLATINUM": POINTS_PER_DOLLAR_PLATINUM,
}

TIER_MULT_BPS_BY_TIER: dict = {
    "STANDARD": TIER_STANDARD_MULT_BPS,
    "GOLD": TIER_GOLD_MULT_BPS,
    "PLATINUM": TIER_PLATINUM_MULT_BPS,
}


# ---------------------------------------------------------------------------
# Points expiration — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "The horizon is exactly three hundred sixty-five days,
# measured as the floor of the difference between the current clock and
# last_qualifying_activity_at in whole days (one day equals eighty-six
# thousand four hundred seconds), and the comparison is
# at-or-greater-than".
EXPIRATION_INACTIVITY_DAYS: int = 365


# ---------------------------------------------------------------------------
# Quarterly activation lead window — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "the current logical clock is strictly before that quarter's
# activation_window_end and at-or-after a point fourteen days before
# activation_window_start (otherwise ERR_ACTIVATION_WINDOW_CLOSED,
# covering both an already-ended quarter and an activation attempt more
# than fourteen days in advance of the quarter's start)".
PRE_ACTIVATION_LEAD_DAYS: int = 14


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "limit, which bounds the page size with a default of 10, a
# minimum of 1, and a maximum of 100; and offset, which skips a number of
# items from the head of the result set with a default of 0 and a
# minimum of 0".
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # PRD §3.2: category code "uppercase A-Z plus underscore".
    "BASE_CATEGORY_CODE": "BASE",
    "GROCERY_CATEGORY_CODE": "GROCERY",
    "ROTATING_CATEGORY_CODE": "ROT_DINING",
    # PRD §3.3: partner code "uppercase A-Z, digits, and underscore".
    "AIRLINE_PARTNER_CODE": "AIR_BLUE",
    "HOTEL_PARTNER_CODE": "HOTEL_PINE",
    # Earn-rate defaults: 100 bps = 1% (PRD §3.4 fallback), 500 bps = 5%
    # (PRD §3.2's "five hundred basis points equals five percent").
    "BASE_RATE_BPS": 100,        # 1.00%
    "GROCERY_RATE_BPS": 500,     # 5.00%
    "DINING_RATE_BPS": 500,      # 5.00%
    # Partner defaults.
    "DEFAULT_CONVERSION_RATIO": 2,    # 2 points per 1 partner unit.
    "DEFAULT_MIN_INCREMENT": 1000,    # 1000-unit blocks.
}


__all__ = [
    "SIGNUP_MIN_SPEND_CENTS",
    "SIGNUP_WINDOW_DAYS",
    "SIGNUP_BONUS_POINTS",
    "BASE_BPS",
    "TIER_GOLD_THRESHOLD_CENTS",
    "TIER_PLATINUM_THRESHOLD_CENTS",
    "TIER_STANDARD_MULT_BPS",
    "TIER_GOLD_MULT_BPS",
    "TIER_PLATINUM_MULT_BPS",
    "MIN_REDEMPTION_POINTS",
    "MIN_REDEMPTION_CENTS",
    "POINTS_PER_DOLLAR_STANDARD",
    "POINTS_PER_DOLLAR_GOLD",
    "POINTS_PER_DOLLAR_PLATINUM",
    "POINTS_PER_DOLLAR_BY_TIER",
    "TIER_MULT_BPS_BY_TIER",
    "EXPIRATION_INACTIVITY_DAYS",
    "PRE_ACTIVATION_LEAD_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
