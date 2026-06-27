"""In-memory data store. Everything lives in process memory and is wiped on every
restart — there is NO persistence, NO seeding, NO preloaded entities. Tests build
all state via the API surface."""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # One dict per entity, keyed by id.
        self.apiaries = {}
        self.registrations = {}
        self.hives = {}
        self.inspections = {}
        self.treatments = {}
        self.honey_lots = {}
        self.harvests = {}
        self.contracts = {}
        self.placements = {}
        self.sales = {}
        self.feedings = {}
        self.requeen_schedules = {}

        # Monotonic insertion counter to provide a stable secondary sort for
        # created_at ties (records created within the same millisecond).
        self._seq = 0

        # Logical clock — startup default 2026-01-01T00:00:00Z (PRD §2.4), never
        # falls back to wall-clock time.
        self.clock = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now_iso(self):
        """Wall-clock timestamp for created_at/updated_at, 3 fractional digits."""
        dt = datetime.now(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


# Single global store instance. Created empty at import time; nothing seeded.
store = Store()
