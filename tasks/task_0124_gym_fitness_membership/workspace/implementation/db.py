"""In-memory data store. All state is wiped on every process start.

Storage is plain Python dicts keyed by id. NOTHING is seeded at import or
startup; every entity is built by the test via the API surface.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.membership_plans = {}
        self.locations = {}
        self.members = {}
        self.class_sessions = {}
        self.bookings = {}
        self.pt_packages = {}
        self.pt_sessions = {}
        self.dues_invoices = {}
        self.guest_passes = {}
        self.check_ins = {}

        # Logical clock. Defaults to wall-clock UTC until set explicitly via
        # POST /_clock/set_current_utc. PRD §2.11.
        self.clock = datetime.now(timezone.utc)

        # Monotonic creation sequence so created_at ordering is total even
        # when the logical clock does not advance between creates. The PRD
        # specifies created_at carries millisecond precision and is a total
        # order; we keep a separate monotonic counter to break ties for sort
        # stability without ever exposing it.
        self._seq = 0


# Singleton store for the process. Reconstructed fresh on every boot.
store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store._seq += 1
    return store._seq


def now():
    return store.clock
