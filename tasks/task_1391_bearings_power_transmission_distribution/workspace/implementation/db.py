"""In-memory store and the logical clock. Starts completely empty on boot —
no seeding, no preload. Tests build all state via the API."""

import threading
from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.products = {}
        self.interchanges = {}
        self.customers = {}
        self.contracts = {}
        self.branches = {}
        self.stocks = {}
        self.price_files = {}
        self.orders = {}
        self.order_lines = {}
        self.reservations = {}
        self.call_outs = {}
        self.agreements = {}
        self.consumptions = {}
        self.claims = {}
        self.returns = {}
        self.shops = {}
        self.referrals = {}
        self.seq = 0  # global insertion counter (tie-break for equal created_at)
        self.clock = CLOCK_DEFAULT
        self.lock = threading.RLock()

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
