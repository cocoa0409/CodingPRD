"""In-memory data store. All state is per-process; nothing is persisted."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.crops = {}
        self.recipes = {}
        self.water_loops = {}
        self.racks = {}
        self.towers = {}
        self.batches = {}
        self.allocations = {}
        self.sanitation_cycles = {}
        self.contracts = {}
        self.shipments = {}
        self.shipment_lines = {}
        self.workers = {}
        self.labor_shifts = {}
        self.shift_assignments = {}
        self.energy_readings = {}
        self.failure_reports = {}
        self.replant_requests = {}
        # Logical farm clock — starts at exactly 2026-08-01T00:00:00Z
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()
