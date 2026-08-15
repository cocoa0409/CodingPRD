"""In-memory data store. Starts empty on every boot — no seeding."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Logical clock: default at startup is exactly 2026-08-01T00:00:00Z.
        # The server never falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.sites = {}
        self.benches = {}
        self.shot_plans = {}
        self.muckpiles = {}
        self.product_specs = {}
        self.stockpiles = {}
        self.gradation_tests = {}
        self.scales = {}
        self.scale_calibrations = {}
        self.plant_runs = {}
        self.freight_zones = {}
        self.sales_orders = {}
        self.scale_tickets = {}
        self.royalty_agreements = {}
        self.royalty_statements = {}
        self.msha_inspections = {}
        self.msha_citations = {}
        self.training_records = {}
        self.reclamation_bonds = {}
        self.truck_queue_entries = {}


db = Store()
