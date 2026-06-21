"""In-memory data store (PRD §2.4).

Every byte of state lives in module-level dicts keyed by id and is wiped on each
process boot (start.sh re-invocation). No entity is seeded, preloaded, or
hardcoded at startup.

Most entities carry the full common-field set: id, created_at, updated_at,
version. Two entities are append-only event logs and carry only id + created_at
(no updated_at, no version): TripSegment and WalletTransaction (PRD §2.4).
"""
import itertools
import uuid

from clock import now_iso


class Store:
    def __init__(self):
        # One dict per entity, keyed by id.
        self.plans = {}
        self.zones = {}
        self.vehicles = {}
        self.riders = {}
        self.trips = {}
        self.trip_segments = {}
        self.technicians = {}
        self.rebalancing_tasks = {}
        self.fines = {}
        self.low_income_applications = {}
        self.wallet_transactions = {}
        self.mds_reports = {}
        # Append-only vehicle status timeline used by the MDS time-weighted
        # availability calculation (PRD §3.8). Each entry is
        # {"vehicle_id", "status", "at" (aware UTC datetime), "_seq"}.
        self.vehicle_status_events = []
        # Monotonic creation sequence so that resources created at the same
        # logical-clock instant retain a deterministic insertion order for
        # created_at-ASC sorting and zone-priority tie-breaks.
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    # Server-minted UUID with no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def stamp_new(obj, versioned=True):
    """Set system-managed common fields on creation (PRD §2.4).

    versioned=True  -> id, created_at, updated_at, version (full common set)
    versioned=False -> id, created_at only (append-only event log)
    """
    ts = now_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["_seq"] = db.next_seq()
    if versioned:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    """Refresh updated_at and bump version on mutation (PRD §2.4)."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
