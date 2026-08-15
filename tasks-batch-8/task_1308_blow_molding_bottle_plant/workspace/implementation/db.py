"""In-memory data store. Fresh, empty state on every process boot.

No seeding: every entity is created via the declared API surface.
"""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # insertion counter; guarantees stable created_at ordering
        self.seq = 0
        # wall-clock timestamp of last minted created_at/updated_at (monotonicity)
        self.last_ts = None
        # logical plant clock; default 2026-08-01T00:00:00Z, never wall clock
        self.logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

        self.customers = {}
        self.freight_rate_cards = {}
        self.bottle_specs = {}
        self.qualification_runs = {}
        self.molds = {}
        self.cavity_blockouts = {}
        self.machine_lines = {}
        self.schedule_slots = {}
        self.material_lots = {}
        self.production_orders = {}
        self.production_runs = {}
        self.quality_test_lots = {}
        self.shipments = {}
        self.dock_appointments = {}


store = Store()
