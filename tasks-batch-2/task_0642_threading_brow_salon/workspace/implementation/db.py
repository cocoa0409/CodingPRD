"""In-memory data store. Every boot is a clean slate — no seeding.

Each collection is a dict keyed by the entity's server-minted id. Entities are
stored as plain dicts. Datetime-typed fields are stored as tz-aware datetimes
and serialized to ISO 8601 strings only at the response boundary.
"""
import uuid

import clock


class Store:
    def __init__(self):
        self.salons = {}
        self.technicians = {}
        self.chairs = {}
        self.members = {}
        self.service_menu_items = {}
        self.add_ons = {}
        self.retail_products = {}
        self.packages = {}
        self.queue_tickets = {}
        self.service_visits = {}
        self.line_items = {}
        self.loyalty_entries = {}
        self._seq = 0

    def next_seq(self):
        """Monotonic insertion sequence — a stable tie-break for created_at order."""
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_create(obj, versioned=True):
    """Apply common system fields at creation time (PRD §2.4)."""
    ts = clock.now()
    obj["created_at"] = ts
    obj["_seq"] = db.next_seq()
    if versioned:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    """Refresh updated_at to the current logical clock and bump version (PRD §2.4/§2.10)."""
    if "version" in obj:
        obj["updated_at"] = clock.now()
        obj["version"] += 1
