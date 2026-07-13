"""In-memory data store + the logical clock.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded here: every entity is created through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

from util import now_iso

# The server boots with its logical clock at exactly this instant and never
# reads the host wall clock for any deadline (PRD 2.4).
BOOT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class DB(object):
    def __init__(self):
        self.stores = {}
        self.products = {}
        self.variants = {}
        self.lots = {}
        self.customers = {}
        self.promotions = {}
        self.orders = {}
        self.order_lines = {}
        self.ledger = {}
        self.artists = {}
        self.bookings = {}
        self.returns = {}
        self.clock = BOOT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = DB()


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    """id + created_at (+ updated_at/version for every resource but the ledger)."""
    rec = {"id": new_id(), "created_at": now_iso()}
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """A mutation — including a derived-field recomputation — refreshes
    updated_at and increments version (PRD 2.5)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 0) + 1


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def in_creation_order(records):
    return sorted(records, key=lambda r: r["_seq"])


def find_lot(store_id, variant_id):
    for lot in db.lots.values():
        if lot["store_id"] == store_id and lot["variant_id"] == variant_id:
            return lot
    return None
