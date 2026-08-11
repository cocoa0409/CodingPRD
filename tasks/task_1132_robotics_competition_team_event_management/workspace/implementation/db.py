"""In-memory data store and logical clock.

Storage is in-memory only (plain dicts). The store starts completely empty on
every boot — no seeding, no files, no caches.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.events = {}
        self.teams = {}
        self.persons = {}
        self.screening_records = {}
        self.milestones = {}
        self.part_orders = {}
        self.robot_inspections = {}
        self.violations = {}
        self.matches = {}
        self.alliances = {}
        self.rounds = {}
        self.breakdowns = {}
        self.queue_slots = {}
        self.reset_logs = {}
        self.awards = {}
        self.interview_slots = {}
        self.travel_bookings = {}
        # Logical clock (PRD 2.9) — used by every temporal rule and for all
        # entity timestamps.
        self.clock = DEFAULT_CLOCK
        # Monotonic creation counter used as a stable tie-break for
        # created_at-ordered lists.
        self.seq = itertools.count(1)


store = Store()
request_lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical time."""
    return store.clock


def iso(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 datetime string; returns tz-aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp_new(row):
    """Populate common system fields on a freshly created entity row."""
    row["id"] = new_id()
    row["created_at"] = now()
    row["updated_at"] = now()
    row["version"] = 1
    row["_seq"] = next(store.seq)
    return row


def stamp_new_breakdown(row):
    """MatchScoreBreakdown carries only id + created_at (no updated_at/version)."""
    row["id"] = new_id()
    row["created_at"] = now()
    row["_seq"] = next(store.seq)
    return row


def touch(row):
    """Bump OCC version and updated_at on a mutated entity."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now()
