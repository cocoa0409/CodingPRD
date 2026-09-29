"""In-memory store, logical clock and common-field bookkeeping.

The store starts EMPTY on every boot: no entity is ever seeded, preloaded or
hardcoded.  Every row is created through a declared endpoint.
"""
import itertools
import uuid
from datetime import datetime, timezone

from flask import g

DEFAULT_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.supply_rooms = {}
        self.items = {}
        self.contracts = {}
        self.contract_lines = {}
        self.formulary_items = {}
        self.lots = {}
        self.orders = {}
        self.order_lines = {}
        self.substitution_requests = {}
        self.recall_notices = {}
        self.routes = {}
        self.claims = {}
        self.clock = DEFAULT_CLOCK_UTC
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------
def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 instant. Raises ValueError when unparseable."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    return store.clock


# --------------------------------------------------------------------------
# entity helpers
# --------------------------------------------------------------------------
def new_entity(fields):
    now = clock_now()
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": iso_ms(now),
        "updated_at": iso_ms(now),
        "version": 1,
    }
    ent.update(fields)
    ent["_seq"] = store.next_seq()
    ent["_created_dt"] = now
    fresh = getattr(g, "fresh", None)
    if fresh is None:
        fresh = set()
        g.fresh = fresh
    fresh.add(ent["id"])
    return ent


def touch(entity):
    """Register an entity as mutated by this request.

    Each mutated entity has its ``version`` advanced by exactly one and its
    ``updated_at`` refreshed once per request, at flush time.
    """
    if entity is None:
        return
    fresh = getattr(g, "fresh", None) or set()
    if entity["id"] in fresh:
        return
    dirty = getattr(g, "dirty", None)
    if dirty is None:
        dirty = {}
        g.dirty = dirty
    dirty[entity["id"]] = entity


def flush():
    dirty = getattr(g, "dirty", None)
    if not dirty:
        return
    stamp = iso_ms(clock_now())
    for ent in dirty.values():
        ent["version"] = ent["version"] + 1
        ent["updated_at"] = stamp
    dirty.clear()


def serialize(entity):
    if entity is None:
        return {}
    return dict((k, v) for k, v in entity.items() if not k.startswith("_"))


def sort_key(entity):
    return (entity["_created_dt"], entity["_seq"])


def by_creation(rows):
    return sorted(rows, key=sort_key)
