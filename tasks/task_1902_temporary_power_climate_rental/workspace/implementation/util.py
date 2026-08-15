"""Logical clock, timestamp, decimal, and id helpers (PRD sections 2.4-2.6)."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5): startup default 2026-08-01T00:00:00Z, never wall time.
# ---------------------------------------------------------------------------
_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
_logical_now = None


def _parse_iso(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def init_clock():
    global _logical_now
    _logical_now = _parse_iso(_STARTUP_DEFAULT)


def now():
    return _logical_now


def set_now(dt):
    global _logical_now
    _logical_now = dt


init_clock()


def parse_ts(value):
    """Parse an ISO 8601 string to an aware UTC datetime; None on failure."""
    return _parse_iso(value)


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return "%s.%03dZ" % (base, dt.microsecond // 1000)


def new_id():
    return str(uuid.uuid4())


def new_req_id():
    return "req_" + uuid.uuid4().hex[:24]


# ---------------------------------------------------------------------------
# Decimal helpers (PRD 2.6: exact integer money; ceil / round-half-up only).
# ---------------------------------------------------------------------------

def D(x):
    return Decimal(str(x))


def round_half_up(d, places):
    quantum = Decimal(1).scaleb(-places)
    return d.quantize(quantum, rounding=ROUND_HALF_UP)


def ceil_int(d):
    return int(d.to_integral_value(rounding=ROUND_CEILING))


def num_out(d):
    """Serialize a Decimal as int when integral, else float."""
    if isinstance(d, Decimal):
        if d == d.to_integral_value():
            return int(d)
        return float(d)
    return d


def as_decimal(v):
    """Coerce a JSON number to Decimal; None when not a number (bool excluded)."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return Decimal(str(v))
        except Exception:
            return None
    return None


def as_int(v):
    """Coerce to int when the value is an integer number; None otherwise."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None
