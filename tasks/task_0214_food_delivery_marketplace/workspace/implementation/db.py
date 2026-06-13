"""In-memory data store. Every dict starts EMPTY on each fresh boot.

No entity is seeded, preloaded, or hardcoded. All state is created by the
tests via the declared API surface.
"""
import datetime
import itertools
import threading
import uuid


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id (UUID string).
        self.zones = {}
        self.restaurants = {}
        self.menu_items = {}
        self.customers = {}
        self.dashers = {}
        self.orders = {}
        self.line_items = {}
        self.deliveries = {}
        self.tip_adjustments = {}
        self.order_issues = {}
        self.earnings_records = {}

        # Monotonic sequence to provide a stable creation order for tie-breaks
        # and default ascending-by-creation list ordering, independent of
        # timestamp collisions within a single millisecond.
        self._seq = itertools.count(1)

        # Logical clock. Starts at real "now" (UTC); settable via /_clock/set.
        self._clock = datetime.datetime.now(datetime.timezone.utc)

        self.lock = threading.RLock()

    # --- id / sequence ---
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)

    # --- clock ---
    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


def new_uuid():
    return str(uuid.uuid4())


# Single global store instance — created empty at import time.
store = Store()
