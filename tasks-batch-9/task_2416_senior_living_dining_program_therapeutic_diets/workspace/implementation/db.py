"""In-memory data store.

Every collection starts empty on every boot.  Nothing is ever seeded,
preloaded or hardcoded -- all entities are created by clients through the
declared endpoints.
"""
import itertools
import uuid

from clock import clock

_seq_counter = itertools.count(1)


class Store(object):
    def __init__(self):
        self.communities = {}
        self.venues = {}
        self.residents = {}
        self.diet_orders = {}
        self.substitution_rules = {}
        self.reservations = {}
        self.menu_cycles = {}
        self.menu_items = {}
        self.extensions = {}
        self.tickets = {}
        self.reconciliations = {}
        self.observations = {}
        self.reviews = {}
        self.temperature_logs = {}
        self.feedback = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def base_row(versioned=True):
    """Common resource properties (PRD 2.4).

    `_seq` is an internal insertion counter used only as a deterministic
    tie-break for `created_at` ordering; it is never serialized.
    """
    stamp = clock.iso()
    row = {"id": new_id(), "created_at": stamp, "_seq": next_seq()}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = clock.iso()
    row["version"] = row["version"] + 1


def snapshot(row, keys):
    return dict((k, row.get(k)) for k in keys)


def touch_if_changed(row, snap):
    for key, old in snap.items():
        if row.get(key) != old:
            touch(row)
            return True
    return False


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
