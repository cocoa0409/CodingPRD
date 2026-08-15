"""Shared helpers: ids, timestamps, logical clock, decimal rounding (PRD 2.5, 2.8)."""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits.

    Used ONLY for the response-envelope meta.api_request_timestamp; every
    business timestamp reads the logical clock instead (PRD 2.5).
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5): startup default exactly 2026-08-01T00:00:00Z; the
# server never falls back to wall-clock time for business timestamps.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # Timestamp comparisons at second precision (PRD 2.8).
    return dt.replace(microsecond=0)


def _fmt_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    def __init__(self):
        self._dt = _parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return _fmt_dt(self._dt)

    def set(self, to_iso8601: str) -> datetime:
        # This PRD defines no regression rejection: the QualityManager sets the
        # clock to the supplied instant and the server returns it.
        self._dt = _parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def parse_datetime(s: str) -> datetime:
    return _parse_dt(s)


def fmt_datetime(dt) -> str:
    if dt is None:
        return None
    return _fmt_dt(dt)


def is_valid_iso_datetime(v) -> bool:
    if not isinstance(v, str) or not v.strip():
        return False
    try:
        _parse_dt(v)
        return True
    except (ValueError, TypeError):
        return False


def dec(value) -> Decimal:
    """Exact decimal construction from an int/float/str JSON number."""
    return Decimal(str(value))


def round1(value: Decimal) -> float:
    """Round half-up to one decimal place (crimp pull forces, PRD 2.8)."""
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def round_half_up_int(value: Decimal) -> int:
    """Round half-up to integer cents (PRD 2.8)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
