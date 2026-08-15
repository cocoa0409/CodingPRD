"""In-memory data store. Starts empty on every boot; no seeding."""

import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.customers = {}
        self.properties = {}
        self.assessments = {}
        self.materials = {}
        self.material_lots = {}
        self.crews = {}
        self.route_sheets = {}
        self.quotes = {}
        self.work_orders = {}
        self.displacement_plans = {}
        self.invoices = {}
        self.warranty_records = {}
        self.warranty_claims = {}
        self.weather_snapshots = {}
        # Logical clock; ISO 8601 string in UTC. Startup default per PRD §2.7.
        self.clock = "2026-08-01T00:00:00Z"


DB = Store()
