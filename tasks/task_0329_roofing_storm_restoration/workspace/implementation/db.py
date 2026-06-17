"""In-memory data store.

All entities live in plain dicts keyed by UUID. The store starts EMPTY on every
process boot — nothing is seeded. Tests construct every entity via the declared
API surface.
"""
import threading
import uuid

from timeutil import now_iso


class Store:
    def __init__(self):
        # one dict per entity collection
        self.jobs = {}
        self.estimators = {}
        self.crews = {}
        self.inspections = {}
        self.estimates = {}
        self.line_items = {}
        self.material_orders = {}
        self.crew_assignments = {}
        self.permits = {}
        self.draws = {}
        self.change_orders = {}
        self.warranties = {}
        self.lock = threading.RLock()

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


def common_create_fields(versioned=True):
    """id, created_at[, updated_at, version] populated at create time."""
    ts = now_iso()
    fields = {
        "id": db.new_id(),
        "created_at": ts,
    }
    if versioned:
        fields["updated_at"] = ts
        fields["version"] = 1
    return fields


def touch(entity):
    """Bump version and refresh updated_at on a mutable entity."""
    entity["version"] = entity.get("version", 0) + 1
    entity["updated_at"] = now_iso()
