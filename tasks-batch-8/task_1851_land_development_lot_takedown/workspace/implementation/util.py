"""Shared helpers: ids, timestamps, the logical clock, money/decimal rounding."""
import random
import string
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


_LAST_TS_MS = 0


def now_ts() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits.

    Used for created_at / updated_at (PRD 2.4). Domain timestamps
    (recorded_at, acquisition_close_date, finalized_at) use the logical clock.
    Monotonic per process: resources created in a burst (e.g. lot generation at
    plat recordation) still order correctly under created_at-ascending sorts.
    """
    global _LAST_TS_MS
    ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if ms <= _LAST_TS_MS:
        ms = _LAST_TS_MS + 1
    _LAST_TS_MS = ms
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5): startup default is exactly 2026-08-01T00:00:00Z and
# never consults the wall clock.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # comparisons at whole-second precision
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def fmt_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_dt(self._dt)

    def today(self) -> date:
        return self._dt.date()

    def set(self, dt: datetime) -> datetime:
        self._dt = dt
        return self._dt


CLOCK = LogicalClock()


def round_half_up_int(numer, denom) -> int:
    """round_half_up(numer / denom) to an integer via exact integer arithmetic."""
    numer = int(numer)
    denom = int(denom)
    if denom == 0:
        raise ZeroDivisionError("denom")
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


def dec_quantize(value: Decimal, places: int) -> Decimal:
    """Round half-up to the given number of decimal places."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
