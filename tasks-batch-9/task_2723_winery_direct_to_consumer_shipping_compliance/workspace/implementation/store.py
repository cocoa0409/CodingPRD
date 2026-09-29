"""In-memory data store.

Every collection starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded: every entity is created by an API call.
"""
import itertools
import uuid

import clock

_seq = itertools.count(1)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.wineries = {}
        self.state_rules = {}
        self.prohibited_zips = {}
        self.carrier_programs = {}
        self.carrier_enrollments = {}
        self.consumers = {}
        self.state_permits = {}
        self.club_subscriptions = {}
        self.orders = {}
        self.order_lines = {}
        self.shipments = {}
        self.compliance_exceptions = {}
        self.ledger_entries = {}
        self.remittances = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def base_row(versioned=True):
    """Common system-managed fields (PRD 2.5)."""
    stamp = clock.now_iso()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "_seq": next_seq(),
    }
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1 (PRD 2.5/2.10)."""
    if row is None:
        return row
    row["updated_at"] = clock.now_iso()
    if "version" in row:
        row["version"] = row["version"] + 1
    return row


def ordered(rows):
    """Default list ordering: created_at ascending, insertion order as tie-break."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
