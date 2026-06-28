"""In-memory data store. Fresh on every process boot — no seeding, no disk."""
import itertools
import threading
import uuid

from response import now_iso


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # One dict per entity collection, keyed by id.
        self.fda_food_codes = {}
        self.inspectors = {}
        self.establishments = {}
        self.plan_reviews = {}
        self.permits = {}
        self.inspection_routes = {}
        self.inspections = {}
        self.violations = {}
        self.closure_orders = {}
        self.complaints = {}
        self.enforcement_cases = {}
        # Logical clock: startup default index 0.
        self.clock_index = 0
        # Monotonic sequence to provide stable creation ordering for sorting,
        # independent of timestamp resolution.
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def new_id(self):
        return str(uuid.uuid4())


store = Store()


def stamp_new(record):
    """Attach the four common system fields on creation."""
    ts = now_iso()
    record["id"] = store.new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = store.next_seq()
    return record


def touch(record):
    """Refresh updated_at and bump version on any mutation."""
    record["updated_at"] = now_iso()
    record["version"] = record["version"] + 1
    return record
