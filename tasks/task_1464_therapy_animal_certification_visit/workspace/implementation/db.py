"""In-memory data store. The store starts empty on every boot; nothing is seeded.

A single shared Store instance lives on the module-level singleton `store`.
All records are plain dicts keyed by UUID strings.
"""
import itertools
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Logical clock: fixed default; never falls back to wall-clock time.
        # Stored as an ISO-8601 UTC string; the canonical start value.
        self.clock_iso = "2026-08-01T00:00:00Z"
        # Entity tables: id -> record dict
        self.handlers = {}
        self.animals = {}
        self.teams = {}
        self.evaluators = {}
        self.evaluations = {}
        self.certifications = {}
        self.vaccinations = {}
        self.facilities = {}
        self.agreements = {}
        self.orientations = {}
        self.policies = {}
        self.waivers = {}
        self.visit_requests = {}
        self.visits = {}
        self.incidents = {}
        self.hour_credits = {}
        # Per-table monotonically increasing sequence for deterministic
        # created_at ordering even within the same millisecond.
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()
