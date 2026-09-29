"""In-memory data store and the logical clock (PRD §2.5, §2.6).

Everything lives in plain Python dicts keyed by id.  Nothing is persisted and
nothing is seeded: the store starts completely empty on every boot and every
record is created through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD §2.5 — before any /_clock/set_current_utc call the logical clock reads
# exactly 2026-08-01T00:00:00Z and the server never falls back to wall time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "sellers",
    "asset_listings",
    "trustee_sales",
    "auction_events",
    "auction_lots",
    "bidders",
    "exclusions",
    "deposit_holds",
    "bids",
    "sale_contracts",
    "offers",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


def now():
    """The logical clock."""
    return store.clock


def set_clock(dt):
    store.clock = dt


def new_id():
    return str(uuid.uuid4())


def new_record(**fields):
    """Create a record carrying the four common system-managed properties."""
    rec = {
        "id": new_id(),
        "created_at": store.clock,
        "updated_at": store.clock,
        "version": 1,
        "_seq": store.next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """A mutation of `rec`: refresh updated_at and bump version by exactly 1."""
    rec["updated_at"] = store.clock
    rec["version"] = rec["version"] + 1
    return rec


def ordered(values):
    """PRD §2.3 — collections are ordered by created_at ascending.

    Because every created_at comes from the logical clock, many records share
    the same instant; insertion order (_seq) is the stable secondary key.
    """
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))
