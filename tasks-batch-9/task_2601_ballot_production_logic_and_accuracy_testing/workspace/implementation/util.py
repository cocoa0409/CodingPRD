"""Clock, identifiers, timestamp formatting/parsing and integer rounding helpers."""

import math
import random
import re
import string
import uuid
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
# Every temporal value the server writes reads this clock, never the wall clock.
DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, 0)

_CLOCK = {"now": DEFAULT_NOW}


def now() -> datetime:
    return _CLOCK["now"]


def set_now(dt: datetime) -> None:
    _CLOCK["now"] = dt


def now_str() -> str:
    return fmt_ts(_CLOCK["now"])


# ---------------------------------------------------------------------------
# Timestamps: ISO 8601 UTC with exactly three fractional digits
# ---------------------------------------------------------------------------

def fmt_ts(dt):
    if dt is None:
        return None
    millis = dt.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, millis,
    )


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_ts(value):
    """Parse an ISO 8601 UTC instant. Returns a naive UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6)) if m.group(6) else 0
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    try:
        dt = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    off = m.group(8)
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        body = off[1:].replace(":", "")
        oh = int(body[:2])
        om = int(body[2:4]) if len(body) > 2 else 0
        dt = dt - sign * timedelta(hours=oh, minutes=om)
    return dt


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

def new_id() -> str:
    """UUID string, no type prefix."""
    return str(uuid.uuid4())


_REQ_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id() -> str:
    return "req_" + "".join(random.choice(_REQ_ALPHABET) for _ in range(20))


# ---------------------------------------------------------------------------
# Integer arithmetic helpers.  All money in this domain is integer cents and
# all rates are integer basis points, so every quotient is resolved with an
# explicit rounding discipline over exact integers -- never floats.
# ---------------------------------------------------------------------------

def round_half_up(numerator: int, denominator: int) -> int:
    """Round numerator/denominator half away from zero."""
    if denominator == 0:
        return 0
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((2 * (-numerator) + denominator) // (2 * denominator))


def ceil_div(numerator: int, denominator: int) -> int:
    return -((-numerator) // denominator)


def floor_div(numerator: int, denominator: int) -> int:
    return numerator // denominator


def floor_minutes(later: datetime, earlier: datetime) -> int:
    """floor((later - earlier) / 60 seconds); may be negative."""
    return int(math.floor((later - earlier).total_seconds() / 60.0))
