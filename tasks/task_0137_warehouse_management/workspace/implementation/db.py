"""In-memory data store. Fresh and empty on every process boot.

No seeding, no preloading, no persistence to disk. Tests build all state
through the declared API surface.
"""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # one dict per entity type, keyed by id
        self.skus = {}
        self.locations = {}
        self.license_plates = {}
        self.inbound_asns = {}
        self.asn_lines = {}
        self.receipt_events = {}
        self.putaway_tasks = {}
        self.outbound_orders = {}
        self.order_lines = {}
        self.allocations = {}
        self.waves = {}
        self.pick_tasks = {}
        self.cycle_counts = {}
        self.replenishment_tasks = {}
        # monotonic creation sequence so created_at ties resolve deterministically
        self._seq = 0
        # test-driven clock; None means "use real wall clock"
        self._clock_override = None

    # --- id / sequence ---
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    # --- clock ---
    def now(self):
        if self._clock_override is not None:
            return self._clock_override
        return datetime.now(timezone.utc)

    def set_clock(self, dt):
        self._clock_override = dt

    def now_iso(self):
        dt = self.now()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


store = Store()
