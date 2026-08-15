"""In-memory data store. Fresh per process; nothing is seeded at startup."""
import itertools
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.data_fields = {}
        self.positions = {}
        self.workers = {}
        self.assignments = {}
        self.change_requests = {}
        self.batches = {}
        self.batch_lines = {}
        self.events = {}
        self.dq_rules = {}
        self.exceptions = {}
        self.grants = {}
        self.audit_entries = {}
        # Monotonic insertion sequence for stable created_at tie-breaking.
        self.seq = itertools.count(1)
        # Logical clock: startup default is exactly 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()
