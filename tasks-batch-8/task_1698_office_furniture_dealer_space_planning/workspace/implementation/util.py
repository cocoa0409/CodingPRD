"""Shared helpers: ids, timestamps, logical clock, date arithmetic, exact rounding."""
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def now_ts() -> str:
    """ISO 8601 UTC wall-clock timestamp with three fractional digits (PRD 2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.7) — drives every date-sensitive business rule.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_instant(s):
    """Parse an ISO 8601 instant; returns an aware UTC datetime (second precision) or None."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0)
    except ValueError:
        return None


def fmt_instant(dt) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    def __init__(self):
        self._dt = parse_instant(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_instant(self._dt)

    def today(self) -> date:
        return self._dt.date()

    def set(self, dt: datetime):
        self._dt = dt


CLOCK = LogicalClock()


def parse_date(s):
    """Strict YYYY-MM-DD parse; returns a date or None."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def round_half_up_int(numer: int, denom: int) -> int:
    """round_half_up(numer/denom) to an integer with exact integer arithmetic."""
    numer = int(numer)
    denom = int(denom)
    if denom == 0:
        raise ZeroDivisionError("denom")
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


def add_calendar_days(anchor: date, days: int) -> date:
    return anchor + timedelta(days=days)


def add_business_days(anchor: date, days: int) -> date:
    """Count Mon-Fri only, starting the day after the anchor (PRD 3.4)."""
    d = anchor
    remaining = days
    while remaining > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            remaining -= 1
    return d
