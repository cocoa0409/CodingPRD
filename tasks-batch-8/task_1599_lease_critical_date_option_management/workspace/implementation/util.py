"""Shared helpers: ids, timestamps, logical clock, calendar arithmetic, integer rounding."""
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
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits.

    Used for created_at / updated_at / meta timestamps (PRD §2.5). Business
    timestamps (sent_at, exercised_at, ...) come from the logical clock instead.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def fmt_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date_value(s) -> date:
    """Accept YYYY-MM-DD or an ISO datetime; return its UTC date."""
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    s = str(s).strip()
    if "T" not in s and " " not in s:
        return date.fromisoformat(s)
    return parse_dt(s).date()


def fmt_date_midnight(d: date) -> str:
    """Date-only values are represented at UTC midnight (PRD §2.8)."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_valid_dateish(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        parse_date_value(s)
        return True
    except Exception:
        return False


class LogicalClock:
    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def today(self) -> date:
        return self._dt.date()

    def now_iso(self) -> str:
        return fmt_dt(self._dt)

    def set(self, to_iso8601: str) -> datetime:
        self._dt = parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def add_years(d: date, years: int) -> date:
    """Calendrical year addition; Feb 29 clamps to Feb 28 on non-leap years."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def round_half_up_int(numer, denom=1) -> int:
    """round_half_up(numer/denom) to an integer using exact integer arithmetic."""
    numer = int(numer)
    denom = int(denom)
    if denom == 0:
        raise ZeroDivisionError("denom")
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


# ---------------------------------------------------------------------------
# Insertion sequence (deterministic tie-break; ids are never used for ordering)
# ---------------------------------------------------------------------------

_seq_counter = [0]


def next_seq() -> int:
    _seq_counter[0] += 1
    return _seq_counter[0]
