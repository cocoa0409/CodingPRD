"""Shared helpers: ids, timestamps, logical clock, exact decimal/fraction math."""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def wall_ts() -> str:
    """ISO 8601 UTC wall-clock timestamp with three fractional digits (envelope meta)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock — all time-dependent behavior uses this, never the wall clock.
# Startup default is exactly 2026-08-01T00:00:00Z. Second precision throughout.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s) -> datetime:
    """Parse an ISO 8601 datetime (Z or offset), normalize to UTC, truncate to
    second precision (all datetime comparisons in the platform are at second
    precision). Raises ValueError on unparseable input."""
    if not isinstance(s, str):
        raise ValueError("datetime must be a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def fmt_dt(dt: datetime) -> str:
    """Canonical rendering for business datetime fields: second precision, Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_dt_full(dt: datetime) -> str:
    """created_at / updated_at rendering: three fractional digits (PRD §2.5)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


class LogicalClock:
    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def set(self, dt: datetime):
        self._dt = dt


CLOCK = LogicalClock()


# ---------------------------------------------------------------------------
# Exact numeric helpers (no float drift for money / temperature deviation)
# ---------------------------------------------------------------------------


def dec(x) -> Decimal:
    """Exact decimal of a JSON number (floats recover via shortest repr)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        raise ValueError("bool is not a number")
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(repr(x))
    return Decimal(str(x))


def round2_half_up(fr: Fraction) -> Decimal:
    """round_half_up of a non-negative exact Fraction to 2 decimal places."""
    scaled = fr * 100
    q = (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)
    return Decimal(q) / Decimal(100)


def round2_float(fr: Fraction) -> float:
    return float(round2_half_up(fr))
