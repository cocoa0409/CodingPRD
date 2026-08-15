"""Shared helpers: ids, timestamps, logical clock, calendar arithmetic, money rounding."""
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
    """ISO 8601 UTC timestamp with three fractional digits (server wall clock)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4): starts at exactly 2026-08-01T00:00:00Z, advanced only
# by POST /vet/_clock/set_current_utc. Never falls back to wall-clock time.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse_dt(s: str) -> datetime:
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
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
        new_dt = _parse_dt(to_iso8601)
        if new_dt < self._dt:
            from errors import raise_error, ERR_INVALID_REQUEST
            raise_error(ERR_INVALID_REQUEST,
                        "to_iso8601 is before the current logical time")
        self._dt = new_dt
        return self._dt


CLOCK = LogicalClock()


def parse_datetime(s: str) -> datetime:
    return _parse_dt(s)


def parse_date(s: str) -> date:
    return date.fromisoformat(str(s).strip())


def fmt_datetime(dt: datetime) -> str:
    return _fmt_dt(dt)


def iso_week_key(dt: datetime):
    """(iso_year, iso_week) for delivery-frequency grouping."""
    iso = dt.isocalendar()
    return (iso[0], iso[1])


def quarter_label(d: date) -> str:
    """Calendar-quarter label like 2026-Q3 for the given date."""
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def round_half_up_int(numer, denom) -> int:
    """round_half_up(numer / denom) to an integer, exact integer arithmetic."""
    numer = int(numer)
    denom = int(denom)
    if denom == 0:
        raise ZeroDivisionError("denom")
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


def touch(record: dict):
    """Every mutation refreshes updated_at and increments version (PRD 2.5)."""
    record["updated_at"] = now_ts()
    record["version"] = int(record.get("version", 0)) + 1
