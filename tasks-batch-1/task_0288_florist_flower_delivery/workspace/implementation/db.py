"""In-memory data store. Starts EMPTY on every process boot — no seeding,
no preloaded entities. All state is constructed by tests via the API surface.
"""
import threading
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with three fractional digits and a 'Z' suffix."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (now.microsecond // 1000)) + "Z"


class Store(object):
    """Holds every collection as a dict keyed by id. Monotonic insertion
    sequence is tracked so list endpoints can sort by creation order
    deterministically (ties on created_at resolve by insertion order)."""

    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        # One dict per entity collection, keyed by id.
        self.customers = {}
        self.zones = {}
        self.arrangements = {}
        self.holiday_windows = {}
        self.florists = {}
        self.orders = {}
        self.wire_fulfillments = {}
        self.delivery_slots = {}
        self.substitutions = {}
        self.claims = {}
        self.recurring_schedules = {}
        # Simulated singleton clock; current_utc is None until set by an operator.
        self.clock = {
            "id": new_id(),
            "created_at": now_iso(),
            "current_utc": None,
        }
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


# Single module-level store instance. NOTHING is inserted here.
store = Store()
