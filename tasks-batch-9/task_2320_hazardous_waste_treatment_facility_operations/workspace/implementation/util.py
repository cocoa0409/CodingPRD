"""Shared primitives: UUIDs, timestamps, calendar math, decimal rounding."""

import calendar
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id():
    """Bare UUID string (no prefix) -- PRD 2.4."""
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# datetime helpers
# --------------------------------------------------------------------------

def parse_dt(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if DATE_RE.match(text):
        try:
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    """Validate a bare calendar date string (YYYY-MM-DD); returns the string."""
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        return None
    try:
        datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return None
    return value.strip()


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (d.microsecond // 1000)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_months(dt, months):
    """Add whole calendar months, clamping the day to the target month length."""
    total = dt.month - 1 + int(months)
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def year_of(dt):
    return dt.astimezone(timezone.utc).year


# --------------------------------------------------------------------------
# decimal helpers -- money is integer cents, ratios/masses fixed-precision.
# Every rounding step is half-up (ties away from zero); never float round().
# --------------------------------------------------------------------------

def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    if isinstance(value, bool):
        return Decimal(int(value))
    return Decimal(str(value))


def half_up_int(value):
    """Round a Decimal/number to a whole number, half away from zero."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def qd(value, places):
    """Quantize to `places` decimals, half-up; returns a Decimal."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def q(value, places):
    """Quantize half-up and hand back a JSON number."""
    if value is None:
        return None
    return float(qd(value, places))


def q1(value):
    return q(value, 1)


def q3(value):
    return q(value, 3)


def q4(value):
    return q(value, 4)


def clamp(value, low, high):
    return max(low, min(high, value))
