"""In-memory data store. Starts completely empty on every boot — no seeding.

Every entity carries the four common fields of PRD §2.4: id (UUID, no prefix),
created_at, updated_at (ISO 8601 UTC, three fractional digits), and version
(integer, +1 on every mutation including cascaded ones). A monotonic _seq
guarantees stable created_at-ascending list order even on timestamp ties.
"""
import threading
import uuid
from decimal import Decimal

from timeutil import CLOCK_START, now_iso


class Store:
    def __init__(self):
        self.requirements = {}
        self.sites = {}
        self.tours = {}
        self.lois = {}
        self.plans = {}
        self.milestones = {}
        self.options = {}
        self.reviews = {}
        self.invoices = {}
        self.seq = 0
        self.clock = CLOCK_START
        self.lock = threading.RLock()


store = Store()


def new_entity(fields):
    store.seq += 1
    ent = dict(fields)
    ent["id"] = str(uuid.uuid4())
    ts = now_iso()
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    ent["_seq"] = store.seq
    return ent


def touch(ent):
    """PRD §2.4 — every mutation refreshes updated_at and increments version,
    including mutations caused by cascades originating on another entity."""
    ent["version"] += 1
    ent["updated_at"] = now_iso()


def public(ent):
    """Serialize an entity: strip internals, Decimal -> float."""
    out = {}
    for k, v in ent.items():
        if k.startswith("_"):
            continue
        if isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def sorted_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
