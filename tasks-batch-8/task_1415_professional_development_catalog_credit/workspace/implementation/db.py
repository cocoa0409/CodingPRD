"""In-memory store, logical clock, id/timestamp helpers.

Storage is in-memory only: plain dicts keyed by id. Nothing is seeded at
startup; every entity is created through the API. The store resets whenever
the process boots (the harness restarts the server per test).
"""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.buildings = {}
        self.employees = {}
        self.budgets = {}
        self.courses = {}
        self.sections = {}
        self.meetings = {}
        self.registrations = {}
        self.attendance = {}          # AttendanceRecord by id
        self.attendance_by_pair = {}  # (registration_id, meeting_id) -> id
        self.surveys = {}
        self.survey_by_registration = {}  # registration_id -> survey id
        self.transcript_entries = {}
        self.workshops = {}
        self.growth_plans = {}
        self.assignments = {}
        self.audit_cases = {}
        # Logical clock: startup default is exactly 2026-08-01T00:00:00Z and
        # never falls back to wall-clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0                      # insertion order tiebreaker
        self.waitlist_counters = {}       # section_id -> next waitlist_seq
        self.lock = threading.RLock()


store = Store()


def now():
    """Current logical time."""
    return store.clock


def wall_now():
    return datetime.now(timezone.utc)


def next_seq():
    store.seq += 1
    return store.seq


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def new_resource():
    """Base fields for a versioned resource."""
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(obj):
    """Every mutation updates updated_at and bumps version."""
    obj["updated_at"] = now()
    obj["version"] += 1


def fiscal_year(dt):
    """July-through-June fiscal year: year if month >= 7 else year - 1."""
    return dt.year if dt.month >= 7 else dt.year - 1
