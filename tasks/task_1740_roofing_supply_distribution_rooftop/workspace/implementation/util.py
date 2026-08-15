"""Shared helpers: ids, timestamps, logical clock, exact integer rounding.

All time-dependent behavior runs on the logical clock (PRD 2.4). The clock
starts at exactly 2026-08-01T00:00:00Z and only moves via
POST /roofing/_clock/set_current_utc. Entity timestamps (created_at,
updated_at, delivered_at, notice_filed_at, registered_at) are logical-clock
values rendered with three fractional digits per PRD 2.5.
"""
import random
import string
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def new_id() -> str:
    """Server-minted UUID with no type prefix (PRD 2.5)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def parse_dt(s: str) -> datetime:
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits (entity timestamp format)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        """Second-precision rendering used for the clock endpoint echo."""
        return self._dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def now_ts(self) -> str:
        """Three-fractional-digit rendering used on resources and meta."""
        return fmt_ts(self._dt)

    def set(self, to_iso8601: str) -> datetime:
        new_dt = parse_dt(to_iso8601)
        if new_dt < self._dt:
            from errors import raise_error, ERR_INVALID_REQUEST
            raise_error(ERR_INVALID_REQUEST,
                        "to_iso8601 is before the current logical clock reading")
        self._dt = new_dt
        return self._dt


CLOCK = LogicalClock()


def round_half_up_int(numer, denom=100) -> int:
    """round_half_up(numer/denom) to an integer with exact integer math."""
    numer = int(numer)
    denom = int(denom)
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


def round_half_down_int(numer, denom=100) -> int:
    """round_half_down(numer/denom) to an integer (surge tier caps, PRD 2.6)."""
    numer = int(numer)
    denom = int(denom)
    if numer >= 0:
        return (2 * numer + denom - 1) // (2 * denom)
    return -((2 * (-numer) + denom - 1) // (2 * denom))
