"""Low-level helpers: ids, timestamps, dates, decimal rounding, local-time geometry.

Every structural choice here traces to PRD.md sections 2.4 (identity/timestamps),
2.9 (precision) and 2.10 (local time geometry).
"""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INT_RE = re.compile(r"^[+-]?\d+$")


def new_id():
    """Server-generated UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


_REQ_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id():
    """`api_request_id` -- always begins with the literal prefix `req_` (PRD 2.2)."""
    return "req_" + "".join(random.choice(_REQ_ALPHABET) for _ in range(20))


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.2/2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime, or None if unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
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
    """Parse a strict YYYY-MM-DD calendar date, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not ISO_DATE_RE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def fmt_date(d):
    return None if d is None else d.isoformat()


def rhu(value, places):
    """Round half up to `places` decimal places (PRD 2.9 -- never banker's rounding)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def dec(value):
    """Coerce a JSON number into an exact Decimal (never via binary float)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def epoch_minutes(dt):
    """floor(epoch seconds / 60) -- PRD 2.10 truncates to whole minutes first."""
    return int(dt.timestamp()) // 60


def local_minute(dt, utc_offset_minutes):
    """local_minute(t) = ((floor(epoch_minutes(t)) + utc_offset_minutes) mod 1440)."""
    return (epoch_minutes(dt) + utc_offset_minutes) % 1440


def local_date(dt, utc_offset_minutes):
    """Apply the fixed offset, then read the calendar date off the shifted instant."""
    return (dt + timedelta(minutes=utc_offset_minutes)).date()


def in_window(minute, start, end):
    """Half-open delivery window (PRD 2.10).

    end > start  -> start <= m < end
    otherwise    -> the window wraps midnight: m >= start or m < end
    """
    if end > start:
        return start <= minute < end
    return minute >= start or minute < end


def completed_years(dob, as_of):
    """Completed age in whole years by calendar comparison."""
    if dob is None or as_of is None:
        return None
    return as_of.year - dob.year - ((as_of.month, as_of.day) < (dob.month, dob.day))


def add_days(dt, days):
    return dt + timedelta(days=days)


def date_midnight(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
