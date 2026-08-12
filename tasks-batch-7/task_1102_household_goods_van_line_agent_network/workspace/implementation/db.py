import threading
from datetime import datetime, timezone


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        # Logical clock: startup default exactly 2026-05-01T00:00:00Z
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.order_seq = 0
        self.agents = {}
        self.customers = {}
        self.tariffs = {}
        self.orders = {}
        self.estimates = {}
        self.assignments = {}
        self.coverages = {}
        self.weight_tickets = {}
        self.reweigh_requests = {}
        self.warehouses = {}
        self.sit_lots = {}
        self.crews = {}
        self.statements = {}
        self.claims = {}
        self.disputes = {}


db = DB()
