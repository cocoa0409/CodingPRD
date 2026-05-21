"""Domain thresholds — numeric constants from PRD calculations.

PRD §2.6: monetary fields are integer whole cents; rounding uses half-up.
PRD §3.1: federal hourly minimum is 725 cents; tipped minimum is 213 cents.
PRD §3.2: punch window is symmetric ±60 minutes around scheduled bounds.
PRD §3.4: detention tier thresholds — 15, 60, 120 minutes.
PRD §3.5: TimeEdit window is asymmetric [scheduled_start - 4h,
          scheduled_end + 6h].
PRD §3.6: weekly OT threshold = 40 hours; CA daily OT threshold = 8h;
          CA daily DT threshold = 12h; OT multiplier = 1.5; DT multiplier = 2.0.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Wage floors — PRD §3.1
# ---------------------------------------------------------------------------
FEDERAL_MINIMUM_WAGE_CENTS: int = 725
FEDERAL_TIPPED_MINIMUM_CENTS: int = 213

# Field length limits — PRD §3.1
FULL_NAME_MIN_LEN: int = 1
FULL_NAME_MAX_LEN: int = 120

# Idempotency key — PRD §3.5
IDEMPOTENCY_KEY_MIN_LEN: int = 1
IDEMPOTENCY_KEY_MAX_LEN: int = 64


# ---------------------------------------------------------------------------
# Time windows — PRD §3.2 and §3.5
# ---------------------------------------------------------------------------
PUNCH_WINDOW_BEFORE_START_MINUTES: int = 60
PUNCH_WINDOW_AFTER_END_MINUTES: int = 60

TIME_EDIT_WINDOW_BEFORE_START_HOURS: int = 4
TIME_EDIT_WINDOW_AFTER_END_HOURS: int = 6


# ---------------------------------------------------------------------------
# Meal break — PRD §3.3
# ---------------------------------------------------------------------------
MEAL_BREAK_FIFTH_HOUR_SECONDS: int = 18000  # 5 hours
MEAL_BREAK_MIN_DURATION_MINUTES: int = 30
MEAL_BREAK_THRESHOLD_HOURS: float = 5.0


# ---------------------------------------------------------------------------
# Detention tiers — PRD §3.4
# ---------------------------------------------------------------------------
DETENTION_TIER_1_MIN_MINUTES: int = 15      # >=15 and <60
DETENTION_TIER_2_MIN_MINUTES: int = 60      # >=60 and <120
DETENTION_TIER_3_MIN_MINUTES: int = 120     # >=120


# ---------------------------------------------------------------------------
# Pay engine — PRD §3.6
# ---------------------------------------------------------------------------
WEEKLY_OT_THRESHOLD_HOURS: float = 40.0
CA_DAILY_OT_THRESHOLD_HOURS: float = 8.0
CA_DAILY_DT_THRESHOLD_HOURS: float = 12.0
OT_MULTIPLIER: float = 1.5
DT_MULTIPLIER: float = 2.0


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — values used by factories when no override is given.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "EMPLOYEE_FULL_NAME": "Test Employee",
    # Base hourly rate of 2000 cents ($20/hr) is the standard test rate.
    "BASE_HOURLY_RATE_CENTS": 2000,
    # Tipped employee defaults — federal tipped minimum 213 cents.
    "TIPPED_CASH_RATE_CENTS": 213,
    # Federal full minimum 725 cents; we use 1500 to make tip-credit math
    # produce non-trivial values per scaffold_difficulty_design recipes.
    "APPLICABLE_MINIMUM_WAGE_CENTS": 1500,
    # Sunday 00:00:00.000 UTC anchor used by workweek-driven fixtures.
    # PRD §3.6: "week_start that must be exactly the Sunday 00:00:00.000
    # UTC of the week".
    "WORKWEEK_ANCHOR": "2026-05-17T00:00:00.000Z",
    "MONDAY_0800": "2026-05-18T08:00:00.000Z",
    "MONDAY_1600": "2026-05-18T16:00:00.000Z",
}


# ---------------------------------------------------------------------------
# Week-day offsets relative to the Sunday workweek anchor.
# PRD §3.6: "the system walks the calendar days from Sunday through
# Saturday in order."
# ---------------------------------------------------------------------------
DAY_OFFSETS_SUN_TO_SAT = {
    "SUN": 0,
    "MON": 1,
    "TUE": 2,
    "WED": 3,
    "THU": 4,
    "FRI": 5,
    "SAT": 6,
}


__all__ = [
    "FEDERAL_MINIMUM_WAGE_CENTS",
    "FEDERAL_TIPPED_MINIMUM_CENTS",
    "FULL_NAME_MIN_LEN",
    "FULL_NAME_MAX_LEN",
    "IDEMPOTENCY_KEY_MIN_LEN",
    "IDEMPOTENCY_KEY_MAX_LEN",
    "PUNCH_WINDOW_BEFORE_START_MINUTES",
    "PUNCH_WINDOW_AFTER_END_MINUTES",
    "TIME_EDIT_WINDOW_BEFORE_START_HOURS",
    "TIME_EDIT_WINDOW_AFTER_END_HOURS",
    "MEAL_BREAK_FIFTH_HOUR_SECONDS",
    "MEAL_BREAK_MIN_DURATION_MINUTES",
    "MEAL_BREAK_THRESHOLD_HOURS",
    "DETENTION_TIER_1_MIN_MINUTES",
    "DETENTION_TIER_2_MIN_MINUTES",
    "DETENTION_TIER_3_MIN_MINUTES",
    "WEEKLY_OT_THRESHOLD_HOURS",
    "CA_DAILY_OT_THRESHOLD_HOURS",
    "CA_DAILY_DT_THRESHOLD_HOURS",
    "OT_MULTIPLIER",
    "DT_MULTIPLIER",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
    "DAY_OFFSETS_SUN_TO_SAT",
]
