"""Numeric, date and timestamp helpers."""

import datetime as _dt
import random
import string
import threading
import time
from decimal import Decimal, ROUND_HALF_UP

_Q4 = Decimal("0.0001")
_Q2 = Decimal("0.01")
_Q1 = Decimal("0.1")
_Q0 = Decimal("1")

_ts_lock = threading.Lock()
_last_ms = [0]


def round4(value):
    return Decimal(value).quantize(_Q4, rounding=ROUND_HALF_UP)


def round2(value):
    return Decimal(value).quantize(_Q2, rounding=ROUND_HALF_UP)


def round1(value):
    return Decimal(value).quantize(_Q1, rounding=ROUND_HALF_UP)


def round0(value):
    return int(Decimal(value).quantize(_Q0, rounding=ROUND_HALF_UP))


def dec(value):
    """Convert an arbitrary JSON number into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def num(value):
    """Render a Decimal/number for JSON: integral values become ints."""
    if value is None:
        return None
    d = dec(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def fnum(value):
    """Render a Decimal for JSON as a float (keeps 0.5 for 0.5000)."""
    if value is None:
        return None
    return float(dec(value))


def now_iso():
    """Strictly monotonic wall-clock audit timestamp, millisecond precision."""
    with _ts_lock:
        ms = int(time.time() * 1000)
        if ms <= _last_ms[0]:
            ms = _last_ms[0] + 1
        _last_ms[0] = ms
    return ms_to_iso(ms)


def ms_to_iso(ms):
    seconds, milli = divmod(ms, 1000)
    base = _dt.datetime.fromtimestamp(seconds, _dt.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        base.year, base.month, base.day, base.hour, base.minute, base.second, milli,
    )


def dt_to_iso(value):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day, value.hour, value.minute,
        value.second, value.microsecond // 1000,
    )


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def parse_datetime(text):
    """Parse an ISO 8601 instant. Returns a naive UTC datetime or None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    return parsed


def parse_date(text):
    """Parse a date-only field. Also tolerates a full ISO instant."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    try:
        return _dt.date.fromisoformat(raw[:10]) if len(raw) == 10 else None
    except ValueError:
        pass
    parsed = parse_datetime(raw)
    return parsed.date() if parsed else None


def date_to_str(value):
    if value is None:
        return None
    return value.isoformat()


def add_days(day, days):
    return day + _dt.timedelta(days=days)
