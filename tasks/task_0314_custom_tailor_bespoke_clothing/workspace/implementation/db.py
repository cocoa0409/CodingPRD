"""In-memory data store. Starts empty on every boot — NO seeding."""
import uuid

from response import now_iso


class Store:
    def __init__(self):
        self.customers = {}
        self.measurement_profiles = {}
        self.fabrics = {}
        self.tailors = {}
        self.fitting_rooms = {}
        self.garment_orders = {}
        self.option_lines = {}
        self.fittings = {}
        self.alteration_tickets = {}
        self.payments = {}
        self.group_orders = {}
        self.pickups = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_create(common_fields=True):
    """Initialize system fields on a freshly created entity."""
    ts = now_iso()
    base = {"id": new_id(), "created_at": ts}
    if common_fields:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def touch(entity):
    """Refresh updated_at and bump version on a mutation (incl. cascades)."""
    if "version" in entity:
        entity["version"] += 1
    if "updated_at" in entity:
        entity["updated_at"] = now_iso()
