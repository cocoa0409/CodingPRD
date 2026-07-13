"""In-memory data store and the logical clock.

Everything lives in process memory only. A fresh process (start.sh re-invocation)
wipes every byte of state. Nothing is seeded at import time.
"""
import itertools
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.reports = {}
        self.clients = {}
        self.accounts = {}
        self.facilities = {}
        self.cases = {}
        self.investigations = {}
        self.placements = {}
        self.freezes = {}
        self._seq = itertools.count(1)
        # Logical clock: sole source of "now"; startup default per PRD 2.5.
        self.clock = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        return next(self._seq)


store = Store()


def new_id():
    return str(uuid.uuid4())
