"""Shared helpers: ids, timestamps, the logical clock, datetime parsing, rounding."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits (created_at /
    updated_at / api_request_timestamp). Distinct from the logical clock."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Datetime parsing / formatting
# ---------------------------------------------------------------------------

def parse_dt(value):
    """Parse an ISO 8601 datetime; naive values are treated as UTC. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    s = value.strip()
    if not s:
        raise ValueError("empty datetime")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt: datetime) -> str:
    """Format a computed instant: seconds precision, milliseconds when present."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Logical clock (PRD 3.10). Startup default is exactly 2026-08-01T00:00:00Z;
# before any set call the clock reads that default and never falls back to
# wall-clock time.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._raw = DEFAULT_CLOCK_ISO
        self._dt = parse_dt(DEFAULT_CLOCK_ISO)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        """Echo of the exact string the clock was last set with (or the default)."""
        return self._raw

    def set(self, to_iso8601: str) -> None:
        self._dt = parse_dt(to_iso8601)
        self._raw = to_iso8601


CLOCK = LogicalClock()

PLACEMENT_VALIDITY_DAYS = 730


# ---------------------------------------------------------------------------
# Rounding discipline (PRD 2.7)
# ---------------------------------------------------------------------------

def rhu_cents(amount_cents: int, pct: int) -> int:
    """round_half_up(amount_cents * pct / 100) — integer cents, exact."""
    return int(
        (Decimal(int(amount_cents)) * Decimal(int(pct)) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def rhu_decimal(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def dec_number(value) -> Decimal:
    """Exact Decimal view of a stored JSON number (int or float)."""
    return Decimal(str(value))


def add_days_iso(raw_iso: str, days: int) -> str:
    return fmt_dt(parse_dt(raw_iso) + timedelta(days=days))
