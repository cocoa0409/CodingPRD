"""Shared helpers: ids, timestamps, the logical clock, calendar arithmetic, money rounding."""
import calendar
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits (meta only)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5). Free-setting: forward and backward both allowed.
# Startup default is exactly 2026-08-01T00:00:00Z.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # Logical-clock comparisons are at whole-second precision
    return dt.replace(microsecond=0)


def _fmt_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    def __init__(self):
        self._dt = _parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return _fmt_dt(self._dt)

    def today(self) -> date:
        return self._dt.date()

    def set(self, to_iso8601: str) -> datetime:
        # Free-setting per PRD 2.5: backward moves are permitted.
        self._dt = _parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def parse_datetime(s: str) -> datetime:
    return _parse_dt(s)


def parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


def fmt_datetime(dt: datetime) -> str:
    return _fmt_dt(dt)


def clock_ts() -> str:
    """Logical-clock timestamp, second precision (captured_at, filed_at, ...)."""
    return _fmt_dt(CLOCK.now())


def stamp() -> str:
    """Logical-clock timestamp with three fractional digits (created_at/updated_at).

    Resource timestamps derive from the logical clock so that deadline arithmetic
    keyed off created_at (e.g. branch_inspection_due_date) stays consistent with
    the clock the tests drive.
    """
    dt = CLOCK.now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


def today() -> date:
    return CLOCK.today()


def add_days(d: date, days: int) -> date:
    return d + timedelta(days=days)


def add_days_dt(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def add_months(d: date, months: int) -> date:
    """Calendrical month addition: 2027-01-31 + 1 month = 2027-02-28."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def round_half_up_int(numer, denom) -> int:
    """round_half_up(numer/denom) to an integer using exact integer arithmetic."""
    numer = int(numer)
    denom = int(denom)
    if denom == 0:
        raise ZeroDivisionError("denom")
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


def is_valid_date_str(v) -> bool:
    if not isinstance(v, str):
        return False
    try:
        date.fromisoformat(v.strip())
        return True
    except (ValueError, TypeError):
        return False


def is_valid_datetime_str(v) -> bool:
    if not isinstance(v, str):
        return False
    try:
        _parse_dt(v)
        return True
    except (ValueError, TypeError):
        return False
