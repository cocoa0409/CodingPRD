"""ISO 8601 UTC instant handling.

PRD 2.4: every instant in a request body or a response is ISO 8601 UTC, and
``created_at`` / ``updated_at`` carry three fractional digits.  Instants that a
client supplied are echoed back exactly as supplied; instants the server derives
are rendered canonically.
"""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ]"
    r"(\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_iso_date(value):
    """Parse a calendar date (or a full instant) into an aware UTC datetime.

    ``installed_on_date`` and ``warranty_expires_on`` are the two date-shaped
    inputs in the PRD — every other temporal field is named ``*_utc``.  A bare
    ``YYYY-MM-DD`` is read as midnight UTC on that day.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _DATE_RE.match(value.strip())
    if not m:
        return parse_iso(value)
    year, month, day = m.groups()
    try:
        return datetime(int(year), int(month), int(day), tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(str(exc))


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _ISO_RE.match(value.strip())
    if not m:
        raise ValueError("not an ISO 8601 UTC instant: %r" % value)
    year, month, day, hour, minute, second, frac, offset = m.groups()
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        dt = datetime(int(year), int(month), int(day), int(hour), int(minute),
                      int(second), micro, tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(str(exc))
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def fmt_ms(dt):
    """Always three fractional digits (the common-field timestamp format)."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000)


def fmt_canonical(dt):
    """Three fractional digits only when the instant carries sub-second detail."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    return fmt_ms(dt)


class Instant:
    """An instant plus the exact string form that should be emitted for it."""

    __slots__ = ("dt", "raw")

    def __init__(self, dt, raw):
        self.dt = dt
        self.raw = raw

    @classmethod
    def from_input(cls, value):
        return cls(parse_iso(value), value.strip())

    @classmethod
    def computed(cls, dt):
        return cls(dt, fmt_canonical(dt))

    @classmethod
    def now(cls):
        dt = datetime.now(timezone.utc)
        return cls(dt, fmt_ms(dt))

    def plus_hours(self, hours):
        micros = int((Decimal(hours) * Decimal(3600) * Decimal(10 ** 6))
                     .to_integral_value())
        return Instant.computed(self.dt + timedelta(microseconds=micros))

    def plus_days(self, days):
        return Instant.computed(self.dt + timedelta(days=days))

    def minus_days(self, days):
        return Instant.computed(self.dt - timedelta(days=days))

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Instant(%s)" % self.raw


def micros_between(a, b):
    delta = b - a
    return delta.days * 86400 * 10 ** 6 + delta.seconds * 10 ** 6 + delta.microseconds


def hours_between(a, b):
    """Exact decimal hours from datetime ``a`` to datetime ``b``."""
    return Decimal(micros_between(a, b)) / Decimal(3600 * 10 ** 6)


def days_between(a, b):
    """Exact decimal days from datetime ``a`` to datetime ``b``."""
    return Decimal(micros_between(a, b)) / Decimal(86400 * 10 ** 6)
