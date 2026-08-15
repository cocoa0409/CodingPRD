"""In-memory data store and the single logical clock.

Storage is Python dicts keyed by id only — no SQLite, no JSON dump, no /tmp
cache, no external persistence. The store starts empty on every boot; nothing
is seeded, preloaded, registered, or hardcoded.
"""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Entity tables: id -> dict record
        self.editions = {}
        self.category_configs = {}
        self.submitters = {}
        self.programmers = {}
        self.submissions = {}
        self.fee_payments = {}
        self.assignments = {}
        self.scores = {}
        self.slates = {}
        self.entries = {}
        self.venues = {}
        self.slots = {}
        self.packages = {}
        self.agreements = {}
        self.jurors = {}
        self.awards = {}
        self.ballots = {}
        # Logical clock: starts exactly at the declared default instant and
        # never reads the wall clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = "2026-08-01T00:00:00Z"
        # Monotonic creation sequence for deterministic ordering/tie-breaks.
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


DB = Store()
