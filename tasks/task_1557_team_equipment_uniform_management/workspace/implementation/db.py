"""In-memory data store. Starts empty on every boot — no seeding.

All entity timestamps (created_at/updated_at and business timestamps) read the
logical clock, never wall-clock time (PRD §2.4). Startup clock is exactly
2026-08-01T00:00:00Z.
"""
import itertools
import uuid
from datetime import datetime

from util import UTC, fmt, fmt_ms

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.players = {}
        self.pools = {}
        self.contracts = {}
        self.orders = {}
        self.kits = {}
        self.gear_items = {}
        self.jobs = {}
        self.events = {}
        self.claims = {}
        self.dispositions = {}
        self.clock = DEFAULT_CLOCK
        self.seq = itertools.count(1)


db = Store()


def clock():
    return db.clock


def set_clock(dt):
    db.clock = dt


def new_id():
    return str(uuid.uuid4())


def stamp(entity):
    """Attach system fields at creation (PRD §2.5): id, created_at, updated_at,
    version starting at 1. _seq is an internal insertion counter used to break
    created_at ties (the logical clock makes same-timestamp creation common)."""
    ts = clock()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next(db.seq)
    return entity


def touch(entity):
    """Every mutation refreshes updated_at and increments version by exactly 1
    (PRD §2.5), including system-driven cascades."""
    entity["updated_at"] = clock()
    entity["version"] += 1


def sorted_all(coll):
    """List order: creation timestamp ascending, insertion order breaks ties."""
    return sorted(coll.values(), key=lambda e: (e["created_at"], e["_seq"]))


def serialize(obj, extra=None):
    out = {}
    for k, v in obj.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            # created_at/updated_at are explicitly specified with three
            # fractional digits (PRD §2.5); other business timestamps render at
            # second granularity.
            out[k] = fmt_ms(v) if k in ("created_at", "updated_at") else fmt(v)
        else:
            out[k] = v
    if extra:
        out.update(extra)
    return out
