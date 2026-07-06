"""In-memory data store for the Participatory Budgeting API.

The store starts EMPTY on every boot. No entities are seeded or hardcoded.
All state is built by clients via the declared API surface.
"""
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Each maps id -> entity dict (entity dicts carry a private "_seq" key
        # recording insertion order, used for created_at-ascending sorting and
        # for the funding-selection created_at tie-break).
        self.budget_cycles = {}
        self.categories = {}
        self.residents = {}
        self.proposals = {}
        self.cost_line_items = {}
        self.ballots = {}
        self.ballot_entries = {}
        self.selection_runs = {}
        self.milestones = {}
        self.report_backs = {}
        self._seq = 0
        # Logical clock: startup default is exactly 2026-03-01T00:00:00Z and it
        # never falls back to real wall-clock time until explicitly moved.
        self.clock = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()
# Serialize all request handling to keep the in-memory mutations consistent.
lock = threading.RLock()
