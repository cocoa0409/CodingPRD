"""Shared helpers: ids, timestamps, logical clock, calendar arithmetic, money rounding."""
import calendar
import random
import string
import uuid
from datetime import date, datetime, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """ISO 8601 UTC timestamp with three fractional digits (wall clock; used only
    for the meta envelope and resource created_at/updated_at audit fields)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5): all date-dependent behavior reads this clock.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._dt = _parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def today(self) -> date:
        return self._dt.date()

    def set(self, to_iso8601: str) -> datetime:
        # Free-setting per PRD §2.5: "advances the clock to a supplied instant".
        self._dt = _parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def round_half_up_int(numer, denom) -> int:
    """round_half_up(numer/denom) to an integer using exact integer arithmetic."""
    numer = int(numer)
    denom = int(denom)
    if denom == 0:
        raise ZeroDivisionError("denom")
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    # symmetric behavior for negatives (not expected for money, but safe)
    return -((2 * (-numer) + denom) // (2 * denom))
