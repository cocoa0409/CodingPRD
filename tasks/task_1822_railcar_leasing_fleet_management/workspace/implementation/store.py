"""In-memory data store + logical clock. No persistence; fresh on every boot."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lessees = {}
        self.railcars = {}
        self.leases = {}
        self.tariffs = {}
        self.assignments = {}
        self.reports = {}
        self.statements = {}
        self.repairs = {}
        self.cleanings = {}
        self.assessments = {}
        self.directives = {}
        self.retrofits = {}
        self.retirements = {}
        self.pools = {}
        self.commitments = {}
        self.seq = 0
        # Logical clock: reads exactly 2026-08-01T00:00:00Z before first set.
        self.clock_dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = "2026-08-01T00:00:00Z"


db = Store()


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current logical clock reading as ISO 8601 UTC with three fractional digits."""
    dt = db.clock_dt
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def today():
    return db.clock_dt.date()


def new_entity(fields):
    """Create a record dict with the standard system-managed properties."""
    ent = dict(fields)
    ent["id"] = new_id()
    ts = now_iso()
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    ent["_created_seq"] = next_seq()
    return ent


def touch(ent):
    """Record a mutation: refresh updated_at and increment version by exactly 1."""
    ent["updated_at"] = now_iso()
    ent["version"] += 1
    ent["_created_seq"]  # creation seq retained for stable sort
