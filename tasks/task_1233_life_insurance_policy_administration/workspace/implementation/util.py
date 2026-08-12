"""Date, time, and decimal helpers.

Rules (PRD §2.4/§2.6):
- all state-machine time comes from the logical clock
- monetary amounts are integer cents, round half-up
- 365-day year everywhere; attained age = floor(days since DOB / 365)
"""
import math
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def fmt_clock(dt):
    """Clock echo format: whole-second style when no fractional part."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ts(dt)


def fmt_date(d):
    return d.strftime("%Y-%m-%d")


def parse_date(value):
    """Parse an ISO calendar date (YYYY-MM-DD). Returns date or None."""
    if isinstance(value, str) and _DATE_RE.match(value):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def parse_datetime(value):
    """Parse an ISO 8601 datetime. Accepts trailing Z or numeric offset.
    A bare date is treated as midnight UTC. Returns aware datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if _DATE_RE.match(s):
        try:
            d = datetime.strptime(s, "%Y-%m-%d").date()
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except ValueError:
            return None
    iso = s
    if iso.endswith("Z") or iso.endswith("z"):
        iso = iso[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(d, months):
    """Calendar-month addition on a date."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    # clamp day to last day of target month
    if month == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, month + 1, 1)
    last_day = (next_first - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


def add_years_365(d, years):
    return d + timedelta(days=365 * years)


def age_years(dob, on_date):
    """Attained age in whole years: days since DOB / 365, floored."""
    return math.floor((on_date - dob).days / 365)


def round_half_up(value):
    """Round a Decimal (or Decimal-compatible) to integer cents, half-up."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value))
