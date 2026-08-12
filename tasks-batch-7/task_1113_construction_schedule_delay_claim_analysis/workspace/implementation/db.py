"""In-memory data store and server logical clock.

The store starts EMPTY on every boot. No seeding of any kind is permitted;
every entity is constructed via the declared API surface.
"""

from datetime import datetime, timezone


class LogicalClock:
    """Server logical clock (PRD §2.4).

    Starts at 2026-05-01T00:00:00Z and NEVER falls back to real wall time;
    it advances only when explicitly set via the test-driving endpoint.
    """

    DEFAULT_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def __init__(self):
        self._now = self.DEFAULT_START

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


class Store:
    def __init__(self):
        self.projects = {}
        self.schedule_versions = {}
        self.activities = {}
        self.relationships = {}
        self.progress_updates = {}
        self.progress_entries = {}
        self.delay_events = {}
        self.eot_requests = {}
        self.acceleration_directives = {}
        self.ld_assessments = {}
        self.seq = 0  # global insertion counter for stable ordering
        self.clock = LogicalClock()

    def next_seq(self):
        self.seq += 1
        return self.seq


# Module-level singleton; a fresh process gets a fresh, empty store.
store = Store()
