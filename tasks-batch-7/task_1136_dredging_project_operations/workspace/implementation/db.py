"""In-memory data store and logical clock.

Storage is process-local Python dicts keyed by id. Nothing is persisted to
disk; every boot starts with an empty store (per-test-server isolation
re-launches the process before every test).
"""
from datetime import datetime, timezone

# PRD section 2.4: startup logical time is exactly 2026-05-01T00:00:00Z and the
# clock never falls back to wall-clock time.
DEFAULT_LOGICAL_NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.projects = {}
        self.permits = {}
        self.reaches = {}
        self.plants = {}
        self.plans = {}
        self.surveys = {}
        self.events = {}
        self.sites = {}
        self.tickets = {}
        self.claims = {}
        self.sightings = {}
        self.readings = {}
        self.certs = {}
        self.logical_now = DEFAULT_LOGICAL_NOW
        # Monotonic insertion counter: stable tie-break for created_at ordering.
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
