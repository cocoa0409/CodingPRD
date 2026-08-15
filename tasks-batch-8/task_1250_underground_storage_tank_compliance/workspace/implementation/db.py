"""In-memory data store and server-held logical clock.

Storage is in-memory only (Python dicts keyed by id). The store starts empty
on every boot; no entity is ever seeded, preloaded, or hardcoded at startup.
"""
import itertools
import threading
from datetime import datetime, timezone

# PRD section 2.4: before any client sets it, the logical clock reads exactly
# 2026-05-01T00:00:00Z and never falls back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = CLOCK_DEFAULT
        self.seq = itertools.count(1)  # insertion sequence; tie-breaks created_at
        self.facilities = {}
        self.tank_systems = {}
        self.components = {}
        self.technicians = {}
        self.service_orders = {}
        self.result_records = {}
        self.deficiencies = {}
        self.submissions = {}
        self.release_detection_records = {}
        self.operators = {}
        self.training_records = {}
        self.release_events = {}
        self.fund_claims = {}


store = Store()

COLLECTIONS = [
    "facilities", "tank_systems", "components", "technicians", "service_orders",
    "result_records", "deficiencies", "submissions", "release_detection_records",
    "operators", "training_records", "release_events", "fund_claims",
]
