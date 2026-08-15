"""In-memory data store and logical clock.

Storage is process-local dictionaries keyed by id. The store starts EMPTY on
every boot -- no seeding, no files, no external persistence. The logical clock
defaults to exactly 2026-08-01T00:00:00Z and is only ever moved by the
administrator clock endpoint; the server never falls back to wall-clock time.
"""

import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.members = {}
        self.memberships = {}
        self.leagues = {}
        self.teams = {}
        self.roster_entries = {}
        self.facilities = {}
        self.games = {}
        self.staff = {}
        self.assignments = {}
        self.injury_reports = {}
        self.equipment_pools = {}
        self.checkouts = {}
        self.lockers = {}
        self.fitness_classes = {}
        self.registrations = {}
        # Monotonic sequence for deterministic tie-breaking when logical
        # timestamps coincide.
        self.seq = 0
        # Logical clock: startup default exactly 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Single process-wide lock so concurrent requests stay atomic.
        self.lock = threading.RLock()

    def next_seq(self):
        self.seq += 1
        return self.seq

    def now(self):
        return self.clock


DB = Store()
