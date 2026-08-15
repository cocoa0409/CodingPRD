"""In-memory data store and the logical clock.

The store starts completely empty on every boot — no seeding of any kind.
The logical clock reads exactly 2026-08-01T00:00:00Z before any set call and
never falls back to wall-clock time.
"""

import itertools
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.cases = {}
        self.members = {}
        self.housing_units = {}
        self.housing_setups = {}
        self.benchmarks = {}
        self.benefit_applications = {}
        self.employment_plans = {}
        self.orientation_sessions = {}
        self.case_notes = {}
        self.case_transfers = {}
        self.federal_reports = {}
        self._seq = itertools.count(1)
        self.clock = DEFAULT_CLOCK


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(store._seq)


def wall_now():
    return datetime.now(timezone.utc)


def clock_dt():
    return store.clock


def clock_date():
    return store.clock.date()


def set_clock(dt):
    store.clock = dt


def stamp_new(rec):
    """Populate the common system fields for a freshly created resource."""
    ts = wall_now()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def stamp_new_note(rec):
    """CaseNote is append-only: id + created_at only (no updated_at/version)."""
    rec["created_at"] = wall_now()
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and increment version on every mutation."""
    rec["updated_at"] = wall_now()
    rec["version"] += 1
