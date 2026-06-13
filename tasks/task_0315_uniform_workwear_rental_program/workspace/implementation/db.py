"""In-memory data store.

Storage is process-local Python dicts keyed by entity id. Nothing is persisted
to disk, nothing is seeded at import or startup. A fresh process (every
per-test-server reboot) starts with every table empty; tests build all state
through the declared API surface.
"""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    # ISO 8601 UTC with exactly three fractional digits (PRD §2.4).
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    """A single namespace of in-memory tables. Re-created per process boot."""

    def __init__(self):
        # Each table is id -> record dict.
        self.accounts = {}
        self.wearers = {}
        self.garment_types = {}
        self.garments = {}
        self.wash_stations = {}
        self.assignments = {}
        self.routes = {}
        self.route_stops = {}
        self.service_visits = {}
        self.service_charges = {}
        # Monotonic sequence to break created_at ties deterministically.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


# Module-level singleton. Bound to the lifetime of this process only.
db = Store()
