"""Shared primitives: identifiers, timestamps, decimal arithmetic."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc


def new_id():
    """Server-minted opaque identifier: a bare UUID string, no prefix."""
    return str(uuid.uuid4())


_REQ_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_REQ_ALPHABET) for _ in range(20))


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now():
    return fmt_dt(datetime.now(UTC))


def parse_dt(value):
    """Parse an ISO 8601 instant that carries a Z suffix. None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.endswith("Z"):
        return None
    core = text[:-1]
    if not core:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(core, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def dt_of(value):
    """Parse a stored canonical timestamp string (assumed valid)."""
    return parse_dt(value)


def minutes_between(start, end):
    """Whole minutes from start to end; may be negative."""
    return int((end - start).total_seconds() // 60)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def date_key(dt):
    """UTC calendar date of an instant, as a sortable string."""
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


def iso_week_bounds(dt):
    """Monday 00:00:00Z of dt's ISO week, and the following Monday (exclusive)."""
    midnight = datetime(dt.year, dt.month, dt.day, tzinfo=UTC)
    monday = midnight - timedelta(days=dt.isoweekday() - 1)
    return monday, monday + timedelta(days=7)


def minute_of_day(dt):
    return dt.hour * 60 + dt.minute


def round_half_up(value, places):
    """Decimal ROUND_HALF_UP to the given number of decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def money(value):
    """Round to whole cents, returning an int."""
    return int(round_half_up(value, 0))


def pct2(numerator, denominator):
    """Percentage to two decimals, ROUND_HALF_UP. Zero denominator yields 0.00."""
    if denominator in (0, None):
        return 0.0
    value = (Decimal(numerator) * Decimal(100)) / Decimal(denominator)
    return float(round_half_up(value, 2))


def dec2(value):
    """Two-decimal quantity exposed as a JSON number."""
    return float(round_half_up(value, 2))
