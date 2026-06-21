"""In-memory data store for the Title Insurance Escrow API.

The store starts EMPTY on every process boot. No entity seeding occurs at
startup; every entity a test needs is constructed via the declared API surface.
All persistence is in-process dicts keyed by id, so a start.sh re-invocation
(per-test-server isolation) wipes all state.
"""

import itertools
import uuid

from clock import clock, format_iso8601_ms


class Store:
    def __init__(self):
        self.agencies = {}
        self.plant_records = {}
        self.orders = {}
        self.title_searches = {}
        self.commitments = {}
        self.exceptions = {}
        self.policies = {}
        self.endorsements = {}
        self.deposits = {}
        self.disbursements = {}
        self.remittances = {}
        self.claims = {}
        self.curative_actions = {}
        # Monotonic per-process counter used purely as a stable tie-break for
        # created_at sort ordering (PRD §2.3: oldest first by created_at). The
        # logical clock does not advance per write, so insertion order breaks
        # ties between resources created at the same logical instant.
        self._seq = itertools.count(1)

    def reset(self):
        self.__init__()


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db._seq)


def now_ts():
    """Creation/mutation timestamps are stamped from the logical clock."""
    return format_iso8601_ms(clock.now())
