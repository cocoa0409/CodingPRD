"""In-memory data store, logical clock, id/timestamp helpers."""

import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_START = "2026-08-01T00:00:00Z"
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock() -> datetime:
    return _clock


def set_clock(dt: datetime) -> None:
    global _clock
    _clock = dt


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def wall_now() -> datetime:
    """Wall-clock timestamp used for created_at / updated_at (monotonic per process)."""
    return datetime.now(timezone.utc)


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_clock(dt: datetime) -> str:
    """Format a logical-clock instant as ISO 8601 UTC. Whole seconds get no
    fractional suffix to match the clock's canonical form (2026-08-01T00:00:00Z);
    instants carrying sub-second precision keep three fractional digits."""
    if dt.microsecond:
        return fmt_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value):
    """Parse an ISO 8601 datetime, accepting a trailing Z. Returns aware datetime
    or None when unparseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_valid_date(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    # strict YYYY-MM-DD shape (strptime is lenient about some forms)
    parts = value.split("-")
    return len(parts) == 3 and len(parts[0]) == 4 and len(parts[1]) == 2 and len(parts[2]) == 2


def days_later(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Stores (start empty on every boot — no seeding)
# ---------------------------------------------------------------------------

cycles = {}
grade_sections = {}
applicants = {}
students = {}
applications = {}
evaluations = {}
test_sessions = {}
aid_applications = {}
contracts = {}
reenrollment_offers = {}

# Sequential creation counter: guarantees a strictly increasing creation order
# even when two resources are created within the same wall-clock millisecond.
_creation_seq = 0


def new_id() -> str:
    return str(uuid.uuid4())


def next_seq() -> int:
    global _creation_seq
    _creation_seq += 1
    return _creation_seq
