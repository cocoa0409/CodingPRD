"""In-memory data store. Starts empty on every boot; never seeded."""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Server-generated wall timestamp for created_at/updated_at fields."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    """Simple dict-of-dicts container keyed by entity id."""

    def __init__(self):
        self.plants = {}
        self.products = {}
        self.stores = {}
        self.drivers = {}
        self.lines = {}
        self.store_orders = {}
        self.production_plans = {}
        self.batches = {}
        self.sanitation_cycles = {}
        self.routes = {}
        self.route_stops = {}
        self.stale_returns = {}
        self.thrift_sales = {}
        self.ingredient_indices = {}
        self.surcharge_schedules = {}
        # Logical clock: starts exactly at 2026-08-01T00:00:00Z, never wall clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def clock_iso(self):
        """Logical clock rendered ISO 8601 UTC, second precision (trailing Z)."""
        return self.clock.strftime("%Y-%m-%dT%H:%M:%SZ")


DB = Store()
