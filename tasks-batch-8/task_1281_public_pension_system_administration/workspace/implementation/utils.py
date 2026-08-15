"""Date, time and decimal helpers implementing PRD-pinned semantics.

All money math uses decimal.Decimal with ROUND_HALF_UP. Dates are
calendar-aware: completed-years age, whole-calendar-months spans, first-of
-month arithmetic, and closed/half-open interval overlap checks.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


# ---------------------------------------------------------------------------
# Parsing / formatting
# ---------------------------------------------------------------------------

def parse_date(value):
    """Parse an ISO calendar date (YYYY-MM-DD). Returns date or None."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def parse_datetime(value):
    """Parse an ISO 8601 datetime (accepts trailing Z). Returns aware UTC
    datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Calendar arithmetic
# ---------------------------------------------------------------------------

def completed_years_between(earlier, later):
    """Completed whole years between two dates (age-style)."""
    years = later.year - earlier.year
    if (later.month, later.day) < (earlier.month, earlier.day):
        years -= 1
    return years


def age_completed(dob, on_date):
    return completed_years_between(dob, on_date)


def age_diff_completed(dob_a, dob_b):
    """Completed years between two birth dates, absolute."""
    if dob_a <= dob_b:
        return completed_years_between(dob_a, dob_b)
    return completed_years_between(dob_b, dob_a)


def whole_months_between(start, end):
    """Whole calendar months between two dates (2025-08-01 -> 2026-08-01 = 12)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def first_of_month(dt):
    return date(dt.year, dt.month, 1)


def add_months_first_of_month(year, month, n):
    """First day of the month n months after (year, month)."""
    total = (year * 12 + (month - 1)) + n
    return date(total // 12, total % 12 + 1, 1)


def add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap target years
        return d.replace(year=d.year + years, day=28)


# ---------------------------------------------------------------------------
# Decimal math (never float for money)
# ---------------------------------------------------------------------------

def dec(value):
    """Exact Decimal from an int or a JSON number (via str to avoid binary
    floating point artefacts)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up_int(value):
    """Round a Decimal to the nearest whole cent, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round a Decimal to two decimal places, half-up (service years)."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
