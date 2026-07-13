"""In-memory data store and the logical clock.

Everything is kept in plain Python dicts keyed by id. The store starts empty
on every process boot; no entities are seeded. Datetime values are held as
aware UTC datetime objects and serialized at the edge.
"""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.landlords = {}
        self.inspectors = {}
        self.properties = {}
        self.licenses = {}
        self.complaints = {}
        self.inspections = {}
        self.checklist_items = {}
        self.violations = {}
        self.notices = {}
        self.condemnation_orders = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def now(self):
        return self.clock

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


store = Store()


def new_entity(collection, fields, common=True):
    """Create an entity dict with common system fields and register it."""
    now = store.now()
    ent = dict(fields)
    ent["id"] = store.new_id()
    ent["created_at"] = now
    ent["_seq"] = store.next_seq()
    if common:
        ent["updated_at"] = now
        ent["version"] = 1
    collection[ent["id"]] = ent
    return ent


def touch(ent):
    """Bump version and updated_at for a mutation/transition."""
    ent["version"] = ent.get("version", 1) + 1
    ent["updated_at"] = store.now()
