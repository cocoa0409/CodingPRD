"""Shared helpers: ids, request ids, timestamps, logical clock, calendar math, rounding."""
import calendar
import random
import re
import string
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


# ---------------------------------------------------------------------------
# Wall-clock timestamps (created_at / updated_at / meta.api_request_timestamp).
# ISO 8601 UTC with exactly three fractional digits, strictly monotonic so that
# created_at ordering always reflects insertion order.
# ---------------------------------------------------------------------------

_ts_lock = threading.Lock()
_last_ts = None


def now_ts() -> str:
    global _last_ts
    with _ts_lock:
        dt = datetime.now(timezone.utc)
        dt = dt.replace(microsecond=(dt.microsecond // 1000) * 1000)
        if _last_ts is not None and dt <= _last_ts:
            dt = _last_ts + timedelta(milliseconds=1)
        _last_ts = dt
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4): starts at exactly 2026-08-01T00:00:00Z and never
# falls back to wall-clock time. Only POST /api/_clock/set_current_utc moves it.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_instant(s):
    """Parse an ISO-8601 instant (or bare date) into an aware UTC datetime.

    Raises ValueError on malformed input.
    """
    if not isinstance(s, str):
        raise ValueError("not a string")
    s = s.strip()
    if _DATE_ONLY_RE.match(s):
        d = date.fromisoformat(s)  # may raise ValueError
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    t = s
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)  # may raise ValueError
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_instant(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


class LogicalClock:
    def __init__(self):
        self._dt = parse_instant(DEFAULT_CLOCK_ISO)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_instant(self._dt)

    def today(self) -> date:
        """All calendar comparisons happen at ISO date (day) granularity."""
        return self._dt.date()

    def set(self, to_iso8601: str) -> datetime:
        self._dt = parse_instant(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def parse_date(s) -> date:
    """Strict ISO date parse. Raises ValueError on malformed input."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    return date.fromisoformat(s.strip())


def fmt_date(d: date) -> str:
    return d.isoformat()


def add_months(d: date, months: int) -> date:
    """Calendar-month addition with day-of-month clamping on overflow."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def last_day_of_month(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


# ---------------------------------------------------------------------------
# Decimal / rounding discipline (PRD 2.6)
# ---------------------------------------------------------------------------

def to_decimal(v) -> Decimal:
    """Convert a JSON number to Decimal without float artifacts."""
    return Decimal(str(v))


def round_half_up_cents(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
