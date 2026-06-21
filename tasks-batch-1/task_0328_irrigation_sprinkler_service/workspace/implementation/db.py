"""In-memory data store.

Every collection is a plain dict keyed by id. The store starts empty on every
process boot — NOTHING is seeded. The test harness (per-test-server isolation)
re-launches start.sh before every test, so a fresh process == fresh state.
"""
import threading
import uuid

from response import now_iso

# A single global lock guards all mutations so cascades stay atomic and the
# OCC version comparison is race-free.
LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.customers = {}
        self.technicians = {}
        self.properties = {}
        self.irrigation_systems = {}
        self.zones = {}
        self.controller_programs = {}
        self.service_quotes = {}
        self.work_orders = {}
        self.maintenance_plans = {}
        self.backflow_tests = {}
        self.routes = {}
        self.route_stops = {}
        # monotonic sequence to order rows created within the same millisecond
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_new(record):
    """Populate the common server-managed fields on a brand-new record."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Register a mutation: refresh updated_at and bump version by one.

    Per PRD §2.4 / §2.7 every mutation — including a pure recompute of a
    derived field — refreshes updated_at and increments version.
    """
    record["updated_at"] = now_iso()
    record["version"] += 1
    return record
