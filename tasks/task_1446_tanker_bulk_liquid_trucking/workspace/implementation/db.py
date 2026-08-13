"""In-memory data store and the server-held logical clock.

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
        self.seq = itertools.count(1)  # insertion sequence -> created_at ASC
        self.customers = {}
        self.products = {}
        self.compat_rules = {}
        self.trailers = {}
        self.drivers = {}
        self.wash_bays = {}
        self.wash_certs = {}
        self.racks = {}
        self.shipments = {}
        self.meter_tickets = {}
        self.delivery_tickets = {}
        self.retain_samples = {}
        self.spill_plans = {}
        self.spill_incidents = {}
        self.agreements = {}


store = Store()

COLLECTIONS = [
    "customers", "products", "compat_rules", "trailers", "drivers",
    "wash_bays", "wash_certs", "racks", "shipments", "meter_tickets",
    "delivery_tickets", "retain_samples", "spill_plans", "spill_incidents",
    "agreements",
]
