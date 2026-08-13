"""In-memory data store and server-held logical clock.

Storage is in-memory only (Python dicts keyed by id). The store starts empty
on every boot; no entity is ever seeded, preloaded, or hardcoded at startup.
"""
import itertools
import threading
from datetime import datetime, timezone

# PRD 2.5: at server startup the logical clock reads exactly
# 2026-08-01T00:00:00Z and never falls back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = CLOCK_DEFAULT
        self.seq = itertools.count(1)  # insertion sequence for stable ordering
        self.buying_points = {}
        self.growers = {}
        self.discount_schedules = {}
        self.loads = {}
        self.grade_sheets = {}
        self.certificates = {}
        self.dryers = {}
        self.dryer_bookings = {}
        self.warehouses = {}
        self.storage_receipts = {}
        self.loan_pledges = {}
        self.sheller_contracts = {}
        self.delivery_calls = {}
        self.allocation_lines = {}
        self.settlements = {}
        self.quota_histories = {}
        self.hull_lots = {}


store = Store()

COLLECTIONS = [
    "buying_points", "growers", "discount_schedules", "loads", "grade_sheets",
    "certificates", "dryers", "dryer_bookings", "warehouses",
    "storage_receipts", "loan_pledges", "sheller_contracts", "delivery_calls",
    "allocation_lines", "settlements", "quota_histories", "hull_lots",
]
