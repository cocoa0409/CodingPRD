"""Logical clock (PRD §2.4) and ISO 8601 helpers.

Timestamp rendering rule adopted here (see the implementation summary):

* ``created_at``, ``updated_at`` and ``meta.api_request_timestamp`` always render
  with exactly three fractional-second digits.
* Every OTHER server-written instant reproduces the logical clock's operator
  string verbatim (if the clock was set to ``2026-03-02T08:00:00Z`` a field
  stamped from it is ``2026-03-02T08:00:00Z``).
* Instants derived by arithmetic inherit their source's fractional-digit style.
* Caller-supplied instants are echoed back verbatim.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

DEFAULT_CLOCK_RAW = "2026-05-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def has_fraction(value):
    """True when an ISO string carries fractional seconds."""
    return isinstance(value, str) and "." in value


def fmt(dt, millis=True):
    """Render an aware datetime as ISO 8601 UTC, with or without .mmm."""
    dt = dt.astimezone(timezone.utc)
    if millis:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_like(dt, source_string):
    """Render ``dt`` using the fractional-digit style of ``source_string``."""
    return fmt(dt, millis=has_fraction(source_string))


def shift(source_string, *, hours=0, days=0, minutes=0):
    """Add a whole offset to an ISO string, inheriting its digit style."""
    base = parse_iso(source_string)
    if base is None:
        return None
    moved = base + timedelta(hours=hours, days=days, minutes=minutes)
    return fmt_like(moved, source_string)


def is_strictly_after(a_string, b_string):
    """True when instant a is strictly after instant b."""
    a = parse_iso(a_string)
    b = parse_iso(b_string)
    if a is None or b is None:
        return False
    return a > b


def elapsed_hours(from_string, to_string):
    a = parse_iso(from_string)
    b = parse_iso(to_string)
    if a is None or b is None:
        return None
    return Decimal((b - a).total_seconds()) / Decimal(3600)


def elapsed_days(from_string, to_string):
    a = parse_iso(from_string)
    b = parse_iso(to_string)
    if a is None or b is None:
        return None
    return Decimal((b - a).total_seconds()) / Decimal(86400)


class LogicalClock(object):
    """The server's logical clock; never falls back to wall-clock time."""

    def __init__(self):
        self.raw = DEFAULT_CLOCK_RAW

    def set(self, raw_string):
        self.raw = raw_string

    def now_raw(self):
        """The operator's clock string, reproduced verbatim."""
        return self.raw

    def now_dt(self):
        return parse_iso(self.raw)

    def now_millis(self):
        """The clock rendered with exactly three fractional digits."""
        return fmt(self.now_dt(), millis=True)


clock = LogicalClock()


def rhu(value, places=0):
    """Round half up to ``places`` decimal places; returns a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exponent = Decimal(1).scaleb(-places)
    return value.quantize(exponent, rounding=ROUND_HALF_UP)
