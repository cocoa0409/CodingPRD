"""In-memory data store, logical clock, and bookkeeping helpers."""
import itertools
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Logical plant clock. Before any set call it reads 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = itertools.count(1)
        self.customers = {}
        self.pallet_accounts = {}
        self.pallet_entries = {}
        self.formulas = {}
        self.reviews = {}
        self.tanks = {}
        self.batches = {}
        self.process_runs = {}
        self.container_lots = {}
        self.lines = {}
        self.runs = {}
        self.fg_lots = {}
        self.zones = {}
        self.orders = {}
        self.ops_runs = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Logical clock timestamp (plant time), formatted per spec."""
    return iso_ms(db.clock)


def stamp(entity):
    """Apply the common bookkeeping quartet on creation."""
    entity["id"] = new_id()
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next(db.seq)
    return entity


def stamp_append_only(entity):
    """PalletEntry / OpsRun carry only id and created_at."""
    entity["id"] = new_id()
    entity["created_at"] = now_iso()
    entity["_seq"] = next(db.seq)
    return entity


def touch(entity):
    """Refresh updated_at and bump version on any mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def trunc_minute(dt):
    return dt.replace(second=0, microsecond=0)
