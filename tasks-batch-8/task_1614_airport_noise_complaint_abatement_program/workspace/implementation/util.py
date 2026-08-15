"""Time, clock, rounding, and quarter utilities.

All timestamps emitted by the server are ISO 8601 UTC with three fractional
digits and a trailing Z. The logical clock starts at 2026-08-01T00:00:00Z and
is advanced only via POST /_clock/set_current_utc.
"""
import re
import threading
from datetime import datetime, timedelta, timezone, date

from decimal import Decimal, ROUND_HALF_UP

_LOCK = threading.Lock()
_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_logical_now = _CLOCK_START


def now():
    """Current logical time (UTC)."""
    with _LOCK:
        return _logical_now


def set_now(dt):
    global _logical_now
    with _LOCK:
        _logical_now = dt


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Parse a YYYY-MM-DD date. Returns a date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")


def parse_quarter_label(value):
    """Validate a YYYY-Qn quarter label. Returns (year, q) or None."""
    if not isinstance(value, str):
        return None
    m = _QUARTER_RE.match(value.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def quarter_bounds(year, q):
    """Half-open quarter window [start, end) in UTC."""
    start_month = (q - 1) * 3 + 1
    start = datetime(year, start_month, 1, tzinfo=timezone.utc)
    if q == 4:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, start_month + 3, 1, tzinfo=timezone.utc)
    return start, end


def quarter_key_of(dt):
    """Quarter label (YYYY-Qn) for a datetime."""
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def round1(value):
    """Round half-up to one decimal place; returns a float with 1dp semantics."""
    d = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(d)


def round_cents(value):
    """Round half-up to whole cents; returns an int."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_request_id():
    import secrets
    return "req_" + secrets.token_hex(8)
