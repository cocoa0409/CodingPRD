"""In-memory data store and the logical plant clock (PRD 2.4).

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded here.  Every record is created by an API call.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4: before any client sets it, the logical clock reads exactly this
# instant, and it never falls back to real wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "furnaces",
    "campaigns",
    "batch_recipes",
    "color_changes",
    "forming_machines",
    "customers",
    "bottle_designs",
    "mold_sets",
    "programs",
    "production_jobs",
    "pack_lots",
    "inspection_results",
    "complaints",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """Every server-stamped instant is read from the logical clock."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    rec = {"id": new_id()}
    if versioned:
        rec["created_at"] = now()
        rec["updated_at"] = now()
        rec["version"] = 1
    else:
        rec["created_at"] = now()
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec, bump=True):
    rec["updated_at"] = now()
    if bump:
        rec["version"] = rec.get("version", 1) + 1


def ordered(records):
    """PRD 2.3: every list endpoint orders by created_at ascending.

    _seq is a stable tie-breaker for records minted on the same logical instant.
    """
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
