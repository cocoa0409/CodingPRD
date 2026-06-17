"""In-memory data store. All entities are kept in Python dicts keyed by id.

The store starts EMPTY on every boot. Nothing is seeded, preloaded, or
hardcoded — every entity is created by tests via the declared API surface.
"""
import uuid
from datetime import datetime, timezone


# Fixed epoch baseline used for Station.current_utc at creation (§2.5).
EPOCH_BASELINE = "1970-01-01T00:00:00.000Z"


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.stations = {}
        self.fuel_grades = {}
        self.tanks = {}
        self.pumps = {}
        self.deliveries = {}
        self.shifts = {}
        self.fuel_transactions = {}
        self.store_transactions = {}
        self.loyalty_accounts = {}
        self.car_wash_codes = {}
        # Monotonic counter to break created_at ties for deterministic sort.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    """UUID with no type prefix (§2.4)."""
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (§2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
