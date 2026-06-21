"""In-memory data store.

ALL state is held in process-local Python dicts keyed by entity id. There is no
persistence of any kind — every boot starts empty. The store is NEVER seeded:
tests construct all entities through the declared API surface.
"""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # one dict per entity type, keyed by id
        self.parks = {}
        self.rate_plans = {}
        self.seasons = {}
        self.cancellation_policies = {}
        self.sites = {}
        self.maintenance_holds = {}
        self.guests = {}
        self.reservations = {}
        self.add_ons = {}
        self.payments = {}
        # monotonic insertion sequence for stable tie-breaking when created_at
        # timestamps collide (same-millisecond creation under test speed).
        self._seq = 0
        # Deterministic test clock (current UTC instant). Defaults to real now
        # until a test sets it via POST /_clock/set.
        self.clock = datetime.now(timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    # Server-minted UUID with no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def now_iso_ms(dt=None):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Single module-level store instance. Empty on every process boot.
store = Store()
