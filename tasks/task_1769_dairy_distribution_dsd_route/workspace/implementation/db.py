"""In-memory data store. Starts empty on every boot; no seeding."""

import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.distributors = {}
        self.routes = {}
        self.drivers = {}
        self.stores = {}
        self.products = {}
        self.standing_pars = {}
        self.pricing_periods = {}
        self.price_announcements = {}
        self.trips = {}
        self.temperature_readings = {}
        self.orders = {}
        self.invoices = {}
        self.returns = {}
        self.credit_memos = {}
        self.crate_transactions = {}
        self.merchandising_sessions = {}
        self.route_sale_listings = {}
        # Monotonic insertion sequence for deterministic created_at tie-breaks.
        self.seq = 0
        # Logical clock; ISO 8601 string in UTC. Startup default per PRD §2.4.
        self.clock = "2026-08-01T00:00:00Z"

    def next_seq(self):
        self.seq += 1
        return self.seq


DB = Store()
