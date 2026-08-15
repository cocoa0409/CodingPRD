"""In-memory data store. Starts empty on every boot — no seeding."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.transmission_models = {}   # id -> dict
        self.hard_parts = {}            # id -> dict
        self.interchange_mappings = {}  # id -> dict
        self.reman_orders = {}          # id -> dict
        self.dyno_bookings = {}         # id -> dict
        self.dyno_test_runs = {}        # id -> dict
        self.core_units = {}            # id -> dict
        self.core_deposit_invoices = {} # id -> dict
        self.warranty_claims = {}       # id -> dict
        # Logical clock: startup default exactly 2026-08-01T00:00:00Z
        self.logical_now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self.logical_now

    def set_now(self, dt):
        self.logical_now = dt


db = Store()
