"""In-memory data store, logical clock, id/sequence generation.

The store starts completely empty on every boot; nothing is seeded.
"""
import threading
import uuid
from datetime import datetime, timezone

from util import fmt_dt

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.technicians = {}
        self.accounts = {}
        self.meters = {}
        self.periods = {}
        self.routes = {}
        self.stops = {}
        self.reads = {}
        self.hazards = {}
        self.work_orders = {}
        self.investigations = {}
        self.campaigns = {}
        self.enrollments = {}
        self.snapshots = {}
        self.seq = 0
        self.clock = CLOCK_DEFAULT
        self.lock = threading.RLock()


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    db.seq += 1
    return db.seq


def now_dt():
    """Current logical-clock instant (never wall-clock)."""
    return db.clock


def now_iso():
    return fmt_dt(db.clock)


def stamp_new(rec):
    """Populate common system fields on a freshly created record."""
    ts = now_iso()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()
