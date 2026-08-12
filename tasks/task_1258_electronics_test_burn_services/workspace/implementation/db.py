"""In-memory data store plus the logical clock. A fresh process starts empty."""
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0
        # Logical clock: startup default is exactly 2026-05-01T00:00:00Z.
        self.clock_dt = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = "2026-05-01T00:00:00Z"
        self.customers = {}
        self.programs = {}
        self.fixtures = {}
        self.chambers = {}
        self.reservations = {}
        self.lots = {}
        self.units = {}
        self.results = {}
        self.authorizations = {}
        self.equipment = {}
        self.maintenance_orders = {}
        self.audits = {}
        self.rma_cases = {}
        self.reviews = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()
