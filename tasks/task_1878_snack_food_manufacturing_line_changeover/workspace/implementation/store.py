import uuid
from datetime import datetime, timezone

from util import iso


class Store:
    """In-memory store. Fresh instance per process boot; no seeding."""

    def __init__(self):
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0
        self.products = {}
        self.lines = {}
        self.oils = {}
        self.oil_by_line = {}
        self.movements = {}
        self.changeovers = {}
        self.runs = {}
        self.checks = {}
        self.shipments = {}
        self.windows = {}
        self.cases = {}
        self.comans = {}
        self.agreements = {}
        self.slots = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


STORE = Store()


def new_entity(store, with_version=True):
    now = iso(store.clock)
    e = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "_seq": store.next_seq(),
    }
    if with_version:
        e["version"] = 1
    return e


def touch(store, e):
    e["updated_at"] = iso(store.clock)
    if "version" in e:
        e["version"] += 1


def sort_key(e):
    return (e["created_at"], e["_seq"])
