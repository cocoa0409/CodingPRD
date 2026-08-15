"""Shared helpers: ids, timestamps, the logical clock, exact rounding."""
import itertools
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
    """Envelope meta timestamp: ISO 8601 UTC wall clock with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 datetime into an aware UTC datetime."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt: datetime) -> str:
    """Logical-clock timestamp format: whole seconds, Z suffix."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def is_valid_iso_datetime(v) -> bool:
    if not isinstance(v, str):
        return False
    try:
        parse_iso(v)
        return True
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5). Startup default is exactly 2026-08-01T00:00:00Z.
# The clock never falls back to wall-clock time; the coordinator may move it
# in either direction via POST /_clock/set_current_utc.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._dt = parse_iso(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_iso(self._dt)

    def set(self, to_iso8601: str) -> datetime:
        self._dt = parse_iso(to_iso8601)
        return self._dt


CLOCK = LogicalClock()

# Monotonic insertion sequence for deterministic tie-breaking.
_seq = itertools.count(1)


def next_seq() -> int:
    return next(_seq)


def round_half_up_div(numer: int, denom: int) -> int:
    """Exact round-half-up of numer/denom to an integer (non-negative inputs)."""
    numer = int(numer)
    denom = int(denom)
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


def share4(numer: int, denom: int) -> Decimal:
    """Population/encounter share at exactly 4 decimal places, round half up."""
    return (Decimal(int(numer)) / Decimal(int(denom))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
