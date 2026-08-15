"""Shared helpers: ids, timestamps, logical clock, datetime math (PRD 2.4, 2.10)."""
import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# Monotonic insertion sequence — stable tiebreak for equal created_at values.
SEQ = itertools.count(1)


def next_seq() -> int:
    return next(SEQ)


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def wall_ts() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits.

    Used for created_at / updated_at / meta.api_request_timestamp — these record
    real server time; only the domain instants enumerated in PRD §2.10 read the
    logical clock.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 datetime (Z or offset); naive values are taken as UTC.

    Comparisons are done at whole-second precision.
    """
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def fmt_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_dt(s: str) -> str:
    """Normalize an ISO input string to the canonical whole-second Z form."""
    return fmt_dt(parse_dt(s))


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.10)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


class LogicalClock:
    """Server-side logical clock. Starts at exactly 2026-08-01T00:00:00Z and is
    only ever moved by POST /stop-loss/_clock/set_current_utc — it never falls
    back to wall-clock time. The set endpoint may move it to any supplied
    instant (test setups routinely move it before the default)."""

    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_dt(self._dt)

    def set(self, to_iso8601: str) -> datetime:
        self._dt = parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)
