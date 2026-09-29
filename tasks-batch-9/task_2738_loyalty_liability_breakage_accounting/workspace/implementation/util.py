"""Logical clock, ISO-8601 formatting, exact rounding helpers.

Every timestamp comparison in this service reads the logical UTC clock, which
starts at exactly 2026-08-01T00:00:00Z on a fresh process and never falls back
to wall-clock time.  Only the response envelope's `api_request_timestamp` is a
real-time value, because it is metadata about the HTTP request rather than a
domain timestamp.
"""
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class LogicalClock(object):
    def __init__(self):
        self.current = CLOCK_DEFAULT

    def now(self):
        return self.current

    def set(self, value):
        self.current = value


clock = LogicalClock()


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})"
    r"(?::(\d{2})(?:[.,](\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or return None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tzpart = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if tzpart and tzpart not in ("Z", "z"):
        sign = 1 if tzpart[0] == "+" else -1
        digits = tzpart[1:].replace(":", "")
        off = timedelta(hours=int(digits[:2]), minutes=int(digits[2:4]))
        base = base - sign * off
    return base


def iso(dt):
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


def real_now():
    return datetime.now(UTC)


def rhu(numerator, denominator):
    """Exact rational division rounded half up (ties away from zero)."""
    q = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def clamp(value, low, high):
    return max(low, min(high, value))


def whole_days_between(later, earlier):
    """floor((later - earlier) / 86400 seconds), floored at 0."""
    delta = (later - earlier).total_seconds()
    if delta <= 0:
        return 0
    return int(delta // 86400)
