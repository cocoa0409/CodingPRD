"""In-memory data store.

Every collection is a plain dict keyed by the row's UUID.  The store starts
empty on every boot; no entity is ever seeded, preloaded or hardcoded here.
"""

import copy
import uuid
from contextlib import contextmanager

import clock


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.vendors = {}
        self.items = {}
        self.specs = {}
        self.charts = {}
        self.mappings = {}
        self.customers = {}
        self.order_lines = {}
        self.return_cases = {}
        self.postings = {}
        self.feedback = {}
        self.policies = {}
        self.interventions = {}
        self.deployments = {}
        self._seq = 0
        self.ops_run_seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(extra=None, with_common=True):
    """A fresh row carrying the four system-managed common properties."""
    now = clock.now()
    row = {"id": new_id(), "created_at": now}
    if with_common:
        row["updated_at"] = now
        row["version"] = 1
    row["_seq"] = db.next_seq()
    if extra:
        row.update(extra)
    return row


def touch(row):
    """Record a mutation: refresh updated_at and bump version by exactly 1."""
    row["updated_at"] = clock.now()
    row["version"] = row["version"] + 1
    return row


def _snapshot(row):
    return copy.deepcopy({k: v for k, v in row.items()
                          if k not in ("updated_at", "version")})


@contextmanager
def mutating(row):
    """Touch ``row`` only if the block actually changed one of its fields.

    PRD 2.4: "A recomputation of a derived field counts as a mutation."  A
    recompute that lands on the values already stored has changed nothing, so it
    is not a mutation.
    """
    before = _snapshot(row)
    yield row
    if _snapshot(row) != before:
        touch(row)


def ordered(rows):
    """Default list ordering: created_at ascending (PRD 2.3), stable on ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
