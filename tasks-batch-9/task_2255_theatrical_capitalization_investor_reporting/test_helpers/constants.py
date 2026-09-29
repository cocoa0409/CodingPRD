"""
Fixed values the PRD pins down, plus the two reusable scenario value sets.

Nothing here is invented: every number is either a documented default, a
documented bound, or a figure the tests deliberately choose in order to land on
a documented threshold. Grouping them here keeps the arithmetic that the tests
assert on visible in one place.
"""

# ─── The logical clock ────────────────────────────────────────────────────
# "On startup that clock reads exactly `2026-08-01T00:00:00Z`".
CLOCK_START_ISO = "2026-08-01T00:00:00Z"
CLOCK_START_DATE = "2026-08-01"

CLOCK_PATH = "/_clock/set_current_utc"


def iso_midnight(date_str: str) -> str:
    """Turn a plain calendar date into the instant the clock endpoint wants."""
    return f"{date_str}T00:00:00Z"


# ─── Pagination bounds ────────────────────────────────────────────────────
# `limit` "defaults to 10, its minimum accepted value is 1, and its maximum
# accepted value is 100"; `offset` "defaults to 0".
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Documented field defaults ────────────────────────────────────────────
DEFAULT_CHANGEOVER_BUFFER_DAYS = 3
DEFAULT_WEEKLY_FIXED_RENT_CENTS = 0
DEFAULT_PRE_RECOUPMENT_POOL_PCT = 0.35
DEFAULT_POST_RECOUPMENT_POOL_PCT = 0.4
DEFAULT_SUBSIDIARY_RIGHTS_INVESTOR_SHARE_PCT = 0.4
DEFAULT_CLOSING_NOTICE_MIN_DAYS = 14
DEFAULT_PERFORMANCES_PER_WEEK = 8

# A UUID that is well formed but belongs to no row of any entity.
UNKNOWN_UUID = "00000000-0000-0000-0000-0000000000ff"


# ─── Scenario A: the depth-test house and show ────────────────────────────
# A 1200-seat house at a 19900-cent top price gives a weekly capacity gross of
# 1200 * 19900 * 8 = 191,040,000 cents.
BELASCO = {
    "name": "Belasco House",
    "seat_count": 1200,
    "top_ticket_price_cents": 19900,
    "changeover_buffer_days": 3,
}

LEDGER = {
    "title": "The Ledger",
    "offering_entity_type": "LP",
    "capitalization_target_cents": 120_000_000,
    "reserve_target_cents": 2_000_000,
    "pre_recoupment_pool_pct": 0.35,
    "post_recoupment_pool_pct": 0.4,
    "subsidiary_rights_investor_share_pct": 0.4,
    "closing_notice_min_days": 14,
}

LEDGER_OPERATING_BUDGET = {
    "weekly_fixed_running_cost_cents": 32_000_000,
    "variable_cost_pct": 0.05,
    "performances_per_week": 8,
}

# Three royalty participants: 4 + 3 + 2 = 9 pool points, fixed percentages
# 0.04 + 0.02 + 0.015 = 0.075 of adjusted gross.
PARTICIPANT_AUTHOR = {
    "participant_name": "A. Author",
    "role": "AUTHOR",
    "fixed_gross_pct": 0.04,
    "pool_points": 4,
    "min_guarantee_cents": 400_000,
}
PARTICIPANT_COMPOSER = {
    "participant_name": "C. Composer",
    "role": "COMPOSER",
    "fixed_gross_pct": 0.02,
    "pool_points": 3,
    "min_guarantee_cents": 250_000,
}
PARTICIPANT_DIRECTOR = {
    "participant_name": "D. Director",
    "role": "DIRECTOR",
    "fixed_gross_pct": 0.015,
    "pool_points": 2,
    "min_guarantee_cents": 150_000,
}
TOTAL_POOL_POINTS = 9

# ─── Scenario B: the breadth-test house and show ──────────────────────────
PALACE = {
    "name": "Palace Theatre",
    "seat_count": 1200,
    "top_ticket_price_cents": 19900,
    "changeover_buffer_days": 3,
    "weekly_fixed_rent_cents": 8_500_000,
}

UNDERSTUDY = {
    "title": "The Understudy",
    "offering_entity_type": "LP",
    "capitalization_target_cents": 120_000_000,
    "reserve_target_cents": 20_000_000,
    "pre_recoupment_pool_pct": 0.35,
    "post_recoupment_pool_pct": 0.4,
    "subsidiary_rights_investor_share_pct": 0.4,
    "closing_notice_min_days": 14,
}

# ─── The standard profitable week ─────────────────────────────────────────
# gross 65,000,000; variable cost 5% -> 3,250,000; adjusted gross 61,750,000;
# royalty base 61,750,000 - 33,500,000 = 28,250,000.
STANDARD_WEEK = {
    "week_ending_date": "2026-09-06",
    "performances": 8,
    "gross_receipts_cents": 65_000_000,
    "paid_attendance": 8_200,
    "running_expenses_cents": 33_500_000,
}
STANDARD_WEEK_VARIABLE_COST_CENTS = 3_250_000
STANDARD_WEEK_ADJUSTED_GROSS_CENTS = 61_750_000
STANDARD_WEEK_ROYALTY_BASE_CENTS = 28_250_000
STANDARD_WEEK_CAPACITY_GROSS_CENTS = 191_040_000

# The unit price that makes one accepted unit fill a 120,000,000 target.
FULL_UNIT_PRICE_CENTS = 120_000_000
HALF_UNIT_PRICE_CENTS = 60_000_000
THIRD_UNIT_PRICE_CENTS = 40_000_000
SIXTH_UNIT_PRICE_CENTS = 20_000_000

OFFERING_WINDOW = {"effective_date": "2026-07-15", "expiration_date": "2026-12-31"}
