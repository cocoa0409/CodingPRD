"""In-memory data store. Starts EMPTY on every boot — no seeding of any kind.
Records are plain dicts; internal keys (created_dt, updated_dt, _ord) are
rendered to created_at/updated_at by the serializers."""
import itertools
import uuid
from datetime import timedelta

from clock import now_dt


class Store:
    def __init__(self):
        self.customers = {}
        self.catalog_items = {}
        self.units = {}
        self.partners = {}
        self.plans = {}
        self.reservations = {}
        self.lines = {}
        self.routes = {}
        self.stops = {}
        self.extensions = {}
        self.claims = {}
        self.recalls = {}
        self.tickets = {}
        self.txns = {}


store = Store()

_ord_counter = itertools.count(1)
_ts_counter = itertools.count(1)


def _now():
    # Microsecond jitter keeps created_at strictly increasing per append even
    # when the logical clock does not advance between writes.
    return now_dt() + timedelta(microseconds=next(_ts_counter) % 1000)


def create_rec(collection, fields):
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["_ord"] = next(_ord_counter)
    ts = _now()
    rec["created_dt"] = ts
    rec["updated_dt"] = ts
    rec["version"] = 1
    collection[rec["id"]] = rec
    return rec


def create_txn(fields):
    """DepositTransaction: append-only, id + created_at only (no updated_at/version)."""
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["_ord"] = next(_ord_counter)
    rec["created_dt"] = _now()
    store.txns[rec["id"]] = rec
    return rec


def bump(rec):
    """Every mutation of a record increments version by exactly one."""
    rec["version"] += 1
    rec["updated_dt"] = _now()


def sorted_ords(records):
    return sorted(records, key=lambda r: r["_ord"])
