"""In-memory data store and server-owned logical clock.

The store starts empty on every boot. No seeding of any kind.
"""
import threading
import uuid
from datetime import datetime, timezone

# PRD section 2.4: before any clock call, the logical clock stands here.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clients = {}
        self.visits = {}
        self.lines = {}
        self.batches = {}
        self.items = {}
        self.zones = {}
        self.volunteers = {}
        self.shifts = {}
        self.signups = {}
        self.partners = {}
        self.vouchers = {}
        self.drives = {}
        self.rotations = {}
        self.recycling = {}
        self.seq = 0  # monotonic insertion counter; stable creation-order tiebreak
        self.clock = INITIAL_CLOCK


store = Store()
lock = threading.RLock()


def now():
    return store.clock


def set_clock(dt):
    store.clock = dt


def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    """Populate the common system fields (PRD section 2.5) on a new record."""
    store.seq += 1
    rec["id"] = new_id()
    rec["created_at"] = now()
    rec["updated_at"] = now()
    rec["version"] = 1
    rec["_seq"] = store.seq
    return rec


def touch(rec):
    """Record a modification: refresh updated_at and increment version."""
    rec["updated_at"] = now()
    rec["version"] += 1
