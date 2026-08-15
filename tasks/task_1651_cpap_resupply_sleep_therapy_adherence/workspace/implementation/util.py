"""Shared helpers: ids, timestamps, the logical clock, calendar arithmetic, rounding."""
import calendar
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _fmt_millis(dt: datetime) -> str:
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_ts() -> str:
    """Envelope meta timestamp (real server time, 3 fractional digits)."""
    return _fmt_millis(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5): governs every date comparison in the system.
# Startup default 2026-08-01T00:00:00Z; once set, never falls back to wall clock.
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


def _fmt_dt_z(dt: datetime) -> str:
    """Canonical UTC rendering: second precision, millis appended only when set."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += f".{dt.microsecond // 1000:03d}"
    return base + "Z"


class LogicalClock:
    def __init__(self):
        self._dt = _parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return _fmt_dt_z(self._dt)

    def today(self) -> date:
        return self._dt.date()

    def set(self, to_iso8601: str) -> datetime:
        self._dt = _parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def logical_ts() -> str:
    """Entity created_at/updated_at timestamp, driven by the logical clock."""
    return _fmt_millis(CLOCK.now())


def today() -> date:
    return CLOCK.today()


def parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


def fmt_date(d: date) -> str:
    return d.isoformat()


def add_days(d: date, days: int) -> date:
    return d + timedelta(days=days)


def add_months(d: date, months: int) -> date:
    """Calendrical month addition with month-end clamping (2026-01-31 + 1 -> 2026-02-28)."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


# ---------------------------------------------------------------------------
# Rounding (PRD 2.8): adherence percentages half-up to 1 decimal; coinsurance
# half-up to a whole cent; all money integer cents.
# ---------------------------------------------------------------------------

def round_half_up_1dp(numer: int, denom: int) -> float:
    """round_half_up(numer / denom * 100, 1) using exact Decimal arithmetic."""
    val = (Decimal(int(numer)) * Decimal(100) / Decimal(int(denom))).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return float(val)


def coinsurance_share_cents(line_total_cents: int, rate: str = "0.20") -> int:
    """round_half_up(line_total_cents * rate) to a whole cent (per-order, not per-unit)."""
    val = (Decimal(int(line_total_cents)) * Decimal(rate)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(val)


def ceil_div(numer: int, denom: int) -> int:
    return -(-int(numer) // int(denom))
