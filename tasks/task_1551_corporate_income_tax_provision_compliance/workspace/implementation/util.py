"""Shared helpers: ids, timestamps, the logical clock, calendar arithmetic, money rounding.

Two time notions are kept strictly apart (PRD §2.4 vs §2.7):
  - created_at / updated_at / api_request_timestamp are server-generated wall-clock
    ISO 8601 UTC timestamps with three fractional digits.
  - Business dates (measured_on, filed_on, opened_on, all deadline/sweep comparisons)
    come from the logical clock, whose startup default is exactly 2026-08-01T00:00:00Z
    and which never falls back to wall-clock.
"""
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
    """ISO 8601 UTC wall-clock timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.7)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def _fmt_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    def __init__(self):
        self._dt = _parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return _fmt_dt(self._dt)

    def today(self) -> date:
        """Date portion of the logical clock — every date-valued rule compares against this."""
        return self._dt.date()

    def set(self, to_iso8601: str) -> datetime:
        """Set the logical clock to the supplied instant. The harness drives the
        clock freely (including backwards relative to the startup default — the
        design fixtures' first act is to set it to 2026-01-05), so only
        malformed input is rejected."""
        from errors import raise_error, ERR_INVALID_REQUEST
        try:
            new_dt = _parse_dt(to_iso8601)
        except (ValueError, AttributeError):
            raise_error(ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 timestamp")
        self._dt = new_dt
        return self._dt


CLOCK = LogicalClock()


# ---------------------------------------------------------------------------
# Date arithmetic on YYYY-MM-DD strings
# ---------------------------------------------------------------------------

def parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


def is_date_str(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        date.fromisoformat(s.strip())
        return True
    except ValueError:
        return False


def fmt_date(d: date) -> str:
    return d.isoformat()


def add_months(d: date, months: int) -> date:
    """Calendrical month addition with day clamping (2027-01-31 + 1mo = 2027-02-28)."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29 -> Feb 28 on non-leap target years
        return d.replace(year=d.year + years, day=28)


def whole_months(d1: date, d2: date) -> int:
    """Whole calendar months from d1 to d2, floored, minimum 0 (UTP interest accrual)."""
    m = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    if d2.day < d1.day:
        m -= 1
    return max(0, m)


def add_days(d: date, days: int) -> date:
    return d + timedelta(days=days)


# ---------------------------------------------------------------------------
# Money rounding (PRD §2.5): exactly one round-half-up at the named step,
# computed with exact integer arithmetic (no floats anywhere).
# ---------------------------------------------------------------------------

def round_half_up_int(numer, denom) -> int:
    """round_half_up(numer / denom) to an integer, i.e. floor(x + 1/2), exact."""
    numer = int(numer)
    denom = int(denom)
    if denom == 0:
        raise ZeroDivisionError("round_half_up_int: zero denominator")
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))
