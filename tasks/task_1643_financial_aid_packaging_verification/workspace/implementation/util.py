"""Shared helpers: ids, timestamps, logical clock, pinned rounding arithmetic.

PRD 2.6: every notion of "now" reads from the server-held logical clock, which
defaults to exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""
import random
import string
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def new_id() -> str:
    """Bare UUID, no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def parse_instant(s):
    """Parse an ISO 8601 timestamp into an aware UTC datetime. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_valid_instant(s) -> bool:
    try:
        parse_instant(s)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2/2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    """Server-held logical clock (PRD 2.6)."""

    def __init__(self):
        self._dt = parse_instant(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_ts(self._dt)

    def set(self, to_iso8601: str) -> datetime:
        """'advance or set' — an arbitrary instant is accepted (PRD 3.6 wording)."""
        self._dt = parse_instant(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def minus_one_year(dt: datetime) -> datetime:
    """Calendar one-year subtraction, clamping Feb 29 (receipt window, rung 12)."""
    try:
        return dt.replace(year=dt.year - 1)
    except ValueError:
        return dt.replace(year=dt.year - 1, day=28)


def round_half_up_div(numer: int, denom: int) -> int:
    """round_half_up(numer / denom) to an integer with exact integer arithmetic."""
    numer = int(numer)
    denom = int(denom)
    if denom <= 0:
        raise ZeroDivisionError("denominator must be positive")
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


def floor_div(numer: int, denom: int) -> int:
    return int(numer) // int(denom)
