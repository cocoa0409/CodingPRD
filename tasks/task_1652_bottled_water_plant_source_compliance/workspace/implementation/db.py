"""In-memory data store and the server-side logical clock.

The store starts empty on every boot — no seeding. All entities are created
exclusively through the declared API surface.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

STARTUP_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = itertools.count(1)
        self.clock = STARTUP_CLOCK
        self.plants = {}
        self.permits = {}
        self.withdrawal_events = {}
        self.treatment_runs = {}
        self.lab_tests = {}
        self.lines = {}
        self.deliveries = {}
        self.lots = {}
        self.recalls = {}
        self.bottles = {}
        self.wash_batches = {}
        self.reports = {}


store = Store()


def logical_now():
    return store.clock


def logical_date():
    return store.clock.date()


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_ts():
    return fmt_ts(datetime.now(timezone.utc))


def new_resource(fields):
    r = dict(fields)
    r["id"] = str(uuid.uuid4())
    now = fmt_ts(store.clock)
    r["created_at"] = now
    r["updated_at"] = now
    r["version"] = 1
    r["_seq"] = next(store.seq)
    return r


def touch(r):
    """Refresh updated_at and increment version by exactly 1."""
    r["updated_at"] = fmt_ts(store.clock)
    r["version"] += 1


def by_creation(items):
    """Sort by created_at ASC; the logical clock ties often, so break ties by
    the global insertion sequence (== creation order)."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
