"""Shared utilities — ID generation, ISO timestamps, half-up rounding, date math.

All monetary operations use Decimal with ROUND_HALF_UP. All datetimes are
timezone-aware UTC.
"""

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

_ALPHANUM = string.ascii_letters + string.digits


def new_uuid() -> str:
    """Generate a server-minted UUID without any prefix."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """Generate an api_request_id of the form req_RANDOMALPHANUM (20 chars after req_)."""
    body = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return f"req_{body}"


def iso_now(now: datetime) -> str:
    """Format a UTC datetime as ISO 8601 with three fractional digits and Z suffix."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    millis = int(now.microsecond / 1000)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso8601(s: str) -> datetime:
    """Parse an ISO 8601 string (UTC). Returns timezone-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    cleaned = s.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Decimal half-up rounding helpers
# ---------------------------------------------------------------------------
def round_half_up_decimal(value: Decimal) -> int:
    """Round a Decimal half-up to the nearest integer."""
    q = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def multiply_and_round(base_cents: int, multiplier_num: int, multiplier_den: int) -> int:
    """Compute round_half_up(base_cents * multiplier_num / multiplier_den).

    This is the pinned-order primitive used by every fee calculation that
    applies the entity multiplier: multiply first, then round once.
    """
    result = (Decimal(base_cents) * Decimal(multiplier_num)) / Decimal(multiplier_den)
    return round_half_up_decimal(result)


# ---------------------------------------------------------------------------
# Date / duration helpers
# ---------------------------------------------------------------------------
def add_days(when: datetime, days: int) -> datetime:
    return when + timedelta(days=days)


def add_years_as_days(when: datetime, years: float) -> datetime:
    """Add a possibly-fractional number of years (PRD §3.4 statutory term).

    Whole-number year shifts use calendar arithmetic (replace the year field)
    which matches the natural-language reading of "plus N years" in patent
    law (granted 2024-01-01 + 20 years = 2044-01-01). Fractional year shifts
    (e.g. the maintenance-window half-year offset) fall back to a 365-day
    approximation since calendar arithmetic is undefined for half-years.
    """
    whole_years = int(years)
    fractional = years - whole_years
    target = when
    if whole_years:
        try:
            target = target.replace(year=target.year + whole_years)
        except ValueError:
            # Feb 29 in a non-leap target year — fall back to Feb 28.
            target = target.replace(year=target.year + whole_years, day=28)
    if fractional:
        target = target + timedelta(seconds=int(fractional * 365.0 * 86400))
    return target


def add_months_30d(when: datetime, months: int) -> datetime:
    """Add `months` calendar months (PRD §3.6 30-month deadline).

    Calendar arithmetic: priority 2024-01-01 + 30 months = 2026-07-01. If
    the day-of-month does not exist in the target month (e.g. Jan 31 +
    1 month), clamp down to the last valid day of that month.
    """
    year_offset, month_index = divmod(when.month - 1 + months, 12)
    target_year = when.year + year_offset
    target_month = month_index + 1
    day = when.day
    # Clamp to last day of target_month
    if target_month == 2:
        last = 29 if (target_year % 4 == 0 and (target_year % 100 != 0 or target_year % 400 == 0)) else 28
    elif target_month in (4, 6, 9, 11):
        last = 30
    else:
        last = 31
    if day > last:
        day = last
    return when.replace(year=target_year, month=target_month, day=day)


def days_between_floor(later: datetime, earlier: datetime) -> int:
    """Return floor((later - earlier) in days). Negative if later < earlier."""
    delta = later - earlier
    total_seconds = delta.total_seconds()
    # Floor toward negative infinity for full-day count
    if total_seconds < 0:
        return -((-int(total_seconds)) // 86400) - (1 if (-int(total_seconds)) % 86400 != 0 else 0)
    return int(total_seconds // 86400)


def ceil_div(numerator: int, denominator: int) -> int:
    """Ceiling division for non-negative numerator (and positive denominator)."""
    if numerator <= 0:
        return 0
    return (numerator + denominator - 1) // denominator
