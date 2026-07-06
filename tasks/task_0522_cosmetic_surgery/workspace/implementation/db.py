"""In-memory data store. Fresh boot wipes all state.

No seeding, preloading, or hardcoded entities. Every entity is created by the
test suite via the declared API surface.
"""
import uuid
from datetime import datetime, timezone

# Logical clock default (PRD §3.10). On startup the clock reads exactly this.
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"


class Store:
    def __init__(self):
        # Each collection: id -> entity dict
        self.procedures = {}
        self.patients = {}
        self.consultations = {}
        self.quote_packages = {}
        self.line_items = {}
        self.consents = {}
        self.clearances = {}
        self.bookings = {}
        self.financings = {}
        self.cases = {}
        # Logical clock, stored as an ISO 8601 UTC string.
        self.clock = CLOCK_DEFAULT


DB = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_create(entity, common=True):
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    if common:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def touch(entity):
    """Mutation bump: refresh updated_at and increment version (PRD §2.5)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
