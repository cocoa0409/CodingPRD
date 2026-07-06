"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid

from clock import clock, format_iso8601


class Store:
    def __init__(self):
        # one dict per entity type, keyed by id
        self.intended_parents = {}
        self.carriers = {}
        self.egg_donors = {}
        self.matches = {}
        self.contracts = {}
        self.escrow_accounts = {}
        self.journeys = {}
        self.milestones = {}
        self.comp_schedules = {}
        self.disbursements = {}
        self.insurance_reviews = {}
        # monotonic creation sequence for stable created_at tie-breaking
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock creation/update timestamp (ISO 8601 UTC, 3 fractional digits)."""
    from datetime import datetime, timezone

    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_create(obj):
    """Attach common create-time system fields."""
    ts = now_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = db.next_seq()
    return obj


def touch(obj):
    """Mutation: bump version and refresh updated_at."""
    obj["version"] = obj.get("version", 1) + 1
    obj["updated_at"] = now_iso()
    return obj
