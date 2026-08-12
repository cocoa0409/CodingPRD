"""In-memory data store. Starts empty on every boot — no seeding.

All entity timestamps (created_at/updated_at and business timestamps) read the
district logical clock, never wall-clock time (PRD §2.4).
"""
import itertools
import uuid
from datetime import datetime

from util import UTC, fmt, fmt_ms

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.students = {}
        self.offense_codes = {}
        self.sanction_bands = {}
        self.cases = {}
        self.notices = {}
        self.conferences = {}
        self.appeals = {}
        self.hearings = {}
        self.evidence_items = {}
        self.mdrs = {}
        self.sites = {}
        self.placements = {}
        self.reentry_plans = {}
        self.expungements = {}
        self.clock = DEFAULT_CLOCK
        self.seq = itertools.count(1)


db = Store()


def clock():
    return db.clock


def set_clock(dt):
    db.clock = dt


def new_id():
    return str(uuid.uuid4())


def stamp(entity, light=False):
    """Attach system fields. Light entities (OffenseCode, SanctionBand) carry
    only id + created_at; everything else also gets updated_at + version."""
    ts = clock()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["_seq"] = next(db.seq)
    if not light:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def touch(entity):
    """Every mutation refreshes updated_at and increments version (PRD §2.5)."""
    entity["updated_at"] = clock()
    entity["version"] += 1


def sorted_all(coll):
    """List order: creation timestamp ascending, insertion order breaks ties
    (the logical clock makes same-timestamp creation common)."""
    return sorted(coll.values(), key=lambda e: (e["created_at"], e["_seq"]))


def serialize(obj, extra=None):
    out = {}
    for k, v in obj.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            # created_at is explicitly specified in PRD §2.5 as carrying three
            # fractional digits; every other business timestamp renders at
            # second granularity.
            out[k] = fmt_ms(v) if k == "created_at" else fmt(v)
        else:
            out[k] = v
    if extra:
        out.update(extra)
    return out
