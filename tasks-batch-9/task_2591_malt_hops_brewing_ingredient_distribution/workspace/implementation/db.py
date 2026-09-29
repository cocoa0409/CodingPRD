"""In-memory data store plus the logical clock.

The store is EMPTY on every boot.  Nothing is seeded, preloaded or hardcoded;
every entity is built by callers through the declared API surface.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

from util import fmt_iso

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOCK = threading.RLock()

COLLECTIONS = (
    "brewers",
    "programs",
    "varieties",
    "contracts",
    "offers",
    "malt_products",
    "malt_lots",
    "strains",
    "recipes",
    "jobs",
    "orders",
    "lines",
    "zones",
    "shipments",
    "readings",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self.clock_raw = None
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The current logical instant.  Never the wall clock."""
    return db.clock


def set_clock(dt, raw=None):
    db.clock = dt
    db.clock_raw = raw


def clock_iso():
    return db.clock_raw if db.clock_raw else fmt_iso(db.clock)


def new_id():
    return str(uuid.uuid4())


def new_entity(with_version=True):
    """A fresh record carrying the common system fields."""
    ent = {
        "id": new_id(),
        "created_at": now(),
        "_seq": db.next_seq(),
        "_raw": {},
    }
    if with_version:
        ent["updated_at"] = now()
        ent["version"] = 1
    return ent


def touch(ent):
    """Record a mutation: refresh updated_at and increment version by one."""
    ent["updated_at"] = now()
    ent["version"] = ent.get("version", 1) + 1


def set_dt(ent, field, dt, raw=None):
    """Store a datetime plus (optionally) the exact string the caller supplied."""
    ent[field] = dt
    raws = ent.setdefault("_raw", {})
    if raw is None:
        raws.pop(field, None)
    else:
        raws[field] = raw


def dt_out(ent, field):
    value = ent.get(field)
    if value is None:
        return None
    raw = ent.get("_raw", {}).get(field)
    if raw:
        return raw
    return fmt_iso(value)


def sort_key(ent):
    """created_at ASC with insertion order as the stable tie-break."""
    return (ent["created_at"], ent["_seq"])


def by_created(items):
    return sorted(items, key=sort_key)
