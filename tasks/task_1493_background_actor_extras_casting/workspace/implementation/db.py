"""In-memory data store, logical clock, and time helpers.

Storage is process-local only: plain dicts keyed by id. No files, no SQLite,
no external persistence — every `start.sh` re-invocation boots an empty store.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.productions = {}
        self.actors = {}
        self.casting_calls = {}
        self.look_requirements = {}
        self.holding_areas = {}
        self.bookings = {}
        self.time_events = {}
        self.vouchers = {}
        self.bump_adjustments = {}
        self.payroll_batches = {}
        self.replacement_cases = {}
        self.standby_entries = {}
        self.ratio_waivers = {}
        self.seq = 0
        # Logical clock default (PRD section 2.5): exactly 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


STORE = Store()


def next_seq():
    STORE.seq += 1
    return STORE.seq


def new_id():
    return str(uuid.uuid4())


def wall_now():
    return datetime.now(timezone.utc)


def logical_now():
    return STORE.clock


def fmt_wall(dt):
    """ISO 8601 UTC with exactly three fractional digits (created_at/updated_at)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    """ISO 8601 UTC for domain datetimes (call_time, deadlines, occurred_at)."""
    if dt is None:
        return None
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += f".{dt.microsecond // 1000:03d}"
    return base + "Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime; returns aware UTC datetime or None on failure."""
    if not isinstance(value, str):
        return None
    t = value.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO calendar date YYYY-MM-DD; returns date or None on failure."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
