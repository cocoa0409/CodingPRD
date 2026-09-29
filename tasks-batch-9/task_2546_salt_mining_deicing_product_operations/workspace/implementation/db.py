"""In-memory store. Starts completely empty on every boot -- nothing is seeded."""

import uuid
from datetime import datetime, timezone

from flask import g

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        self.mines = {}
        self.panels = {}
        self.inspections = {}
        self.runs = {}
        self.batches = {}
        self.depots = {}
        self.lots = {}
        self.shipments = {}
        self.forecasts = {}
        self.contracts = {}
        self.orders = {}
        self.allocations = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def now():
    """The logical clock -- never the wall clock."""
    return store.clock


def new_id():
    return str(uuid.uuid4())


def stamp(kind_seq=True):
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(obj):
    """Refresh updated_at and bump version -- at most once per request per entity."""
    if obj is None:
        return
    try:
        touched = g._touched
    except AttributeError:
        touched = g._touched = set()
    key = obj["id"]
    if key in touched:
        return
    touched.add(key)
    obj["version"] = obj.get("version", 1) + 1
    obj["updated_at"] = now()


def by_seq(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def by_seq_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
