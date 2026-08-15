"""Dates, timestamps, decimals, ids."""
import calendar
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id():
    return str(uuid.uuid4())


def now_dt():
    """Current logical-clock instant (UTC)."""
    return db.get_clock()


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits, from the clock."""
    dt = now_dt().astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def today():
    """Clock date (UTC)."""
    return now_dt().astimezone(timezone.utc).date()


def today_str():
    return today().isoformat()


def parse_date(value):
    """Strict YYYY-MM-DD -> date, or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_instant(value):
    """ISO 8601 instant -> aware UTC datetime, or None. Date-only = midnight UTC."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if _DATE_RE.match(text):
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def iso_instant(dt):
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def add_months(d, months):
    """Add months keeping day-of-month; clamp to month end when needed."""
    total = d.year * 12 + (d.month - 1) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_days(d, days):
    return d + timedelta(days=days)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def round_half_up_int(numer, denom):
    """round(numer/denom, 0) half-up -> int."""
    return int((Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(numer, denom):
    """round(numer/denom, 4) half-up -> Decimal quantized to 4dp."""
    return (Decimal(numer) / Decimal(denom)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def q4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def num4(value):
    """Serialize a 4dp Decimal as a JSON number."""
    return float(q4(value))
