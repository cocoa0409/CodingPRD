"""In-memory data store.

Plain Python dicts keyed by id.  Nothing is persisted, nothing is seeded: the
store is empty on every boot and every row is created through the declared API
surface.  `_seq` is a global insertion counter used as a stable tie-break for
list ordering (created_at values can tie when the logical clock is not moved
between creates).
"""

import itertools
import uuid

import clock as clockmod

COLLECTIONS = (
    "distributors",
    "core_returns",
    "core_deposits",
    "build_specs",
    "work_orders",
    "operations",
    "components",
    "engines",
    "dyno_tests",
    "warranty_claims",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self._engine_serial = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def next_engine_serial(self):
        """'RMN-' + 6-digit zero-padded sequence in creation order."""
        return "RMN-%06d" % next(self._engine_serial)


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_new(record, versioned=True):
    """Attach the common creation fields (PRD 2.4).  DynoTest is the single
    exception: it carries only id and created_at (versioned=False)."""
    record["id"] = new_id()
    record["created_at"] = clockmod.now()
    record["_seq"] = db.next_seq()
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and increment version on a mutated row (PRD 2.4).
    Every mutation of a resource -- including cascade writes to a parent --
    is a first-class mutation with a refreshed updated_at and a version bump."""
    if "version" in record:
        record["updated_at"] = clockmod.now()
        record["version"] += 1
    return record


def order_key(record):
    """Default list ordering: created_at ascending, stable by insertion."""
    return (record["created_at"], record["_seq"])


def sorted_rows(rows):
    return sorted(rows, key=order_key)
