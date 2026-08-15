"""In-memory data store and server-held logical clock.

Storage is in-memory only (Python dicts keyed by id). The store starts empty
on every boot; no entity is ever seeded, preloaded, or hardcoded at startup.
"""
import itertools
import threading
from datetime import datetime, timezone

# PRD section 2.5: at server startup the logical clock reads exactly
# 2026-05-01T00:00:00Z and never falls back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = CLOCK_DEFAULT
        self.seq = itertools.count(1)  # insertion sequence for created_at ordering
        self.buildings = {}
        self.rooms = {}
        self.groups = {}
        self.participants = {}
        self.revisions = {}
        self.assignments = {}
        self.screenings = {}
        self.turn_tasks = {}
        self.linen_issues = {}
        self.key_credentials = {}
        self.damage_assessments = {}
        self.invoices = {}
        self.maintenance_windows = {}
        self.allocation_runs = {}


store = Store()

COLLECTIONS = [
    "buildings", "rooms", "groups", "participants", "revisions", "assignments",
    "screenings", "turn_tasks", "linen_issues", "key_credentials",
    "damage_assessments", "invoices", "maintenance_windows", "allocation_runs",
]
