"""In-memory data store + logical clock. No persistence; fresh on every boot.

The store starts empty — every entity is constructed via the declared API
surface. The logical clock (PRD 2.5) reads exactly 2026-08-01T00:00:00Z at
startup and is only moved by POST /sustainability/_clock/set_current_utc.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.sites = {}
        self.factors = {}
        self.cycles = {}
        self.records = {}
        self.evidence = {}
        self.inventories = {}
        self.engagements = {}
        self.targets = {}
        self.instruments = {}
        self.questionnaires = {}
        self.seq = 0
        # Logical clock: exactly 2026-08-01T00:00:00Z before any clock call.
        self.clock_dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Current logical clock reading (never wall-clock)."""
    return fmt_dt(db.clock_dt)


def new_entity(fields):
    """Create a record dict with the standard system-managed properties."""
    ent = dict(fields)
    ent["id"] = new_id()
    ts = now_iso()
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    ent["_seq"] = next_seq()
    return ent


def touch(ent):
    """Record a mutation: refresh updated_at and increment version by exactly 1."""
    ent["updated_at"] = now_iso()
    ent["version"] += 1
