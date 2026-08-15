"""In-memory data store. Starts empty on every boot; no seeding."""

import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.tours = {}
        self.shows = {}
        self.products = {}
        self.show_products = {}
        self.allocations = {}
        self.sellers = {}
        self.sessions = {}
        self.sale_records = {}
        self.online_orders = {}
        self.settlements = {}
        self.shipments = {}
        # Logical clock per PRD §2.6; startup default 2026-08-01T00:00:00Z.
        self.clock = "2026-08-01T00:00:00Z"


DB = Store()
