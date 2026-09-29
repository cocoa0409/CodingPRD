"""In-memory data store.

Storage is process-local Python dicts keyed by id.  Nothing is persisted and
nothing is ever seeded: the store starts completely empty on every boot and all
state is built by callers through the declared API surface.
"""

import itertools
import uuid

from flask import g

from clock import clock


class Store(object):
    """Every collection is a dict id -> record (a plain dict)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.licenses = {}
        self.beams = {}
        self.cells = {}
        self.plans = {}
        self.subscribers = {}
        self.orders = {}
        self.terminals = {}
        self.scans = {}
        self.subscriptions = {}
        self.usage_records = {}
        self.roaming = {}
        self.outage_events = {}
        self.outage_credits = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def _touched_set():
    marker = getattr(g, "_touched_records", None)
    if marker is None:
        marker = set()
        g._touched_records = marker
    return marker


def new_record(with_common_fields=True):
    """Mint a record.  `version` starts at 1 and `created_at` is logical now."""
    now = clock.now()
    record = {"id": new_id(), "created_at": now, "_seq": db.next_seq()}
    if with_common_fields:
        record["updated_at"] = now
        record["version"] = 1
    try:
        _touched_set().add(id(record))
    except RuntimeError:  # pragma: no cover - outside a request context
        pass
    return record


def touch(record):
    """Mark a record mutated: refresh `updated_at` and bump `version` by 1.

    A record mutated several times inside one request (a cell whose counters are
    recomputed by both a cancellation and the promotion that cancellation
    triggers, for instance) advances its `version` by exactly 1 for that
    request, which is what every state-machine side-effect list specifies.
    """
    if record is None:
        return
    record["updated_at"] = clock.now()
    if "version" not in record:
        return
    try:
        seen = _touched_set()
    except RuntimeError:  # pragma: no cover
        record["version"] = record.get("version", 1) + 1
        return
    key = id(record)
    if key in seen:
        return
    seen.add(key)
    record["version"] = record.get("version", 1) + 1


def ordered(records):
    """Default collection order: created_at ascending (PRD 2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
