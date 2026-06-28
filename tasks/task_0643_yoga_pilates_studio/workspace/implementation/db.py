"""In-memory data store.

All state lives in plain dicts keyed by id. Nothing is seeded at construction —
every entity is built by the test suite through the declared API surface. A fresh
Store() is created at process boot, so all state is wiped on every restart.
"""
import uuid
import threading

from clock import LogicalClock, format_iso_ms


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = LogicalClock()

        # One dict per entity, keyed by id.
        self.members = {}
        self.rooms = {}
        self.teachers = {}
        self.intro_offers = {}
        self.class_sessions = {}
        self.entitlements = {}
        self.reservations = {}
        self.fee_charges = {}
        self.workshops = {}
        self.enrollments = {}

        # Monotonic insertion sequence to provide a stable created_at ordering
        # tie-breaker even when multiple records share the same logical-clock ms.
        self._seq = 0

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now_iso(self):
        return format_iso_ms(self.clock.now())


# Global singleton store, recreated fresh on each process boot.
store = Store()
