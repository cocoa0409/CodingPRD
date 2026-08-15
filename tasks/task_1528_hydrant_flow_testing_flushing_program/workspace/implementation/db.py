"""In-memory data store. Everything lives in module-level Python dicts inside a
single Store instance. The store starts EMPTY on every process boot: no seeding,
no files, no SQLite, no persistence of any kind. The per-test-server isolation
of the harness re-launches start.sh (a fresh Python process) before every test,
so every test sees a pristine store."""
import itertools
import uuid
from datetime import datetime, timezone

INITIAL_CLOCK_ISO = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        # Entity tables: id -> record dict
        self.programs = {}
        self.zones = {}
        self.private_owners = {}
        self.hydrants = {}
        self.inspections = {}
        self.flow_tests = {}
        self.flush_sequences = {}
        self.complaints = {}
        self.outages = {}
        self.work_orders = {}
        self.parts = {}
        self.iso_snapshots = {}
        # Global monotonic insertion sequence (tiebreak for created_at ordering)
        self.seq = itertools.count(1)
        # The logical clock. Exactly 2026-08-01T00:00:00Z before any call and
        # never falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = INITIAL_CLOCK_ISO  # echoed by the clock endpoint


store = Store()


def now():
    return store.clock


def new_base():
    """Common fields for every entity: id, created_at, updated_at, version."""
    ts = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(store.seq),
    }


def touch(entity):
    """Register a mutation: refresh updated_at and increment version."""
    entity["updated_at"] = now()
    entity["version"] += 1


def reset():
    """Re-initialize the store (used only by tests of this module itself)."""
    global store
    store = Store()
    return store
