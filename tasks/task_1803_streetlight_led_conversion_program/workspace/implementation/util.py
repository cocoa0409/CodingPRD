"""Shared helpers: ids, request ids, the logical clock, calendar math, rounding.

PRD 2.4: the system never reads wall-clock time; every date/datetime
derivation reads the server-side logical clock, whose pre-set value is
exactly 2026-08-01T00:00:00Z.
"""
import calendar
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 datetime (Z or offset) into an aware UTC datetime."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt: datetime) -> str:
    """Render aware UTC datetime as ISO 8601 Z. Seconds precision when the
    value lands on a whole second (so round-trips of `to_iso8601` match
    byte-for-byte), otherwise three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += "." + f"{dt.microsecond // 1000:03d}"
    return base + "Z"


def fmt_ts(dt: datetime) -> str:
    """Entity/meta timestamp renderer: ISO 8601 UTC, three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_dt(self._dt)

    def now_ts(self) -> str:
        return fmt_ts(self._dt)

    def today(self) -> date:
        return self._dt.date()

    def current_month(self) -> str:
        return self._dt.strftime("%Y-%m")

    def set(self, to_iso8601: str) -> datetime:
        self._dt = parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


def add_one_month(period: str) -> str:
    """'2026-08' -> '2026-09'; '2026-12' -> '2027-01'."""
    y = int(period[:4])
    m = int(period[5:7])
    m += 1
    if m > 12:
        m = 1
        y += 1
    return f"{y:04d}-{m:02d}"


def period_bounds(period: str):
    """Return (p_start, p_end, days_in_month) for a YYYY-MM period."""
    y = int(period[:4])
    m = int(period[5:7])
    d = calendar.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, d), d


def rhu_int(numer, denom) -> int:
    """round_half_up(numer / denom) to an integer, exact via Decimal."""
    return int((Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_decimal(value, places: str) -> Decimal:
    return Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)
