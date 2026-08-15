"""Shared helpers: ids, request ids, logical clock, timestamps, exact rounding."""
import calendar
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def wall_now_iso() -> str:
    """Wall-clock ISO 8601 UTC with three fractional digits (meta timestamps)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _parse_dt(s) -> datetime:
    if not isinstance(s, str):
        raise ValueError("not an ISO datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_dt(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


class LogicalClock:
    """Server logical clock (PRD 2.8). Boots at 2026-08-01T00:00:00Z."""

    def __init__(self):
        self._dt = _parse_dt(DEFAULT_CLOCK_ISO)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return _fmt_dt(self._dt)

    def set(self, iso: str) -> datetime:
        self._dt = _parse_dt(iso)
        return self._dt


CLOCK = LogicalClock()


def parse_dt(s) -> datetime:
    return _parse_dt(s)


def fmt_dt(dt: datetime) -> str:
    return _fmt_dt(dt)


def is_valid_iso_datetime(s) -> bool:
    try:
        _parse_dt(s)
        return True
    except Exception:
        return False


def dec(v) -> Decimal:
    """JSON number -> exact Decimal (via shortest-repr string)."""
    return Decimal(str(v))


def round_half_up_decimal(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_div(numer, denom) -> int:
    """Exact round_half_up(numer / denom) for integers; symmetric on negatives."""
    numer = int(numer)
    denom = int(denom)
    if denom == 0:
        raise ZeroDivisionError("round_half_up_div: zero denominator")
    if denom < 0:
        numer, denom = -numer, -denom
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


def quarter_end_date(year: int, q: int) -> date:
    m = q * 3
    return date(year, m, calendar.monthrange(year, m)[1])


def current_quarter(dt: datetime):
    return dt.year, (dt.month - 1) // 3 + 1


def full_quarters_elapsed(start: datetime, as_of: datetime) -> int:
    """Full calendar quarters between start and as_of (PRD 3.8).

    A quarter is full when the as-of date has reached or passed the end of the
    calendar quarter that follows the quarter containing `start`.
    """
    y, q = start.year, (start.month - 1) // 3 + 1
    q += 1
    if q == 5:
        y, q = y + 1, 1
    count = 0
    while True:
        if as_of.date() >= quarter_end_date(y, q):
            count += 1
            q += 1
            if q == 5:
                y, q = y + 1, 1
        else:
            break
    return count


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def add_hours(dt: datetime, hours: int) -> datetime:
    return dt + timedelta(hours=hours)
