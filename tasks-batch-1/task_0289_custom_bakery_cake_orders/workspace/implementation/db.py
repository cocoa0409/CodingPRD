"""In-memory data store. Everything is a plain dict keyed by id.

The store starts EMPTY on every process boot. No seeding, no preload.
All entities are created via the API surface by the tests.
"""
import uuid

import clock


class Store:
    def __init__(self):
        # Each is a dict: id -> entity dict.
        self.products = {}
        self.options = {}
        self.production_days = {}
        self.routes = {}
        self.customers = {}
        self.orders = {}
        self.lines = {}
        self.proofs = {}
        self.payments = {}
        self.reservations = {}
        # Minted manager-override tokens: token -> scope.
        self.override_tokens = {}

    # -- id / timestamp helpers -------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def stamp_create(self, obj, common_fields=True):
        ts = clock.iso_millis()
        obj["id"] = self.new_id()
        obj["created_at"] = ts
        if common_fields:
            obj["updated_at"] = ts
            obj["version"] = 1
        return obj

    def touch(self, obj):
        """Refresh updated_at and bump version on a mutation."""
        obj["updated_at"] = clock.iso_millis()
        obj["version"] = obj.get("version", 1) + 1


# A single module-level store instance. Recreated fresh each process start.
store = Store()
