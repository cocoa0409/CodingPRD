"""In-memory data store.

Storage is pure Python dictionaries. The store is empty on every boot -- no
entity is ever seeded, preloaded or hardcoded at startup.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD section 2.5: the logical clock's startup value is exactly this instant.
CLOCK_STARTUP = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "operators",
    "manufacturers",
    "distribution_centers",
    "products",
    "contracts",
    "contract_tiers",
    "dc_coverages",
    "deviation_agreements",
    "substitution_rules",
    "price_change_notices",
    "rebate_periods",
    "order_lines",
    "bill_back_claims",
    "bill_back_remittances",
    "pricing_disputes",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self.clock = CLOCK_STARTUP


db = Store()


def wall_now():
    return datetime.now(timezone.utc)


def clock():
    return db.clock


def set_clock(value):
    db.clock = value


def insert(collection, record):
    record["id"] = str(uuid.uuid4())
    stamp = wall_now()
    record["created_at"] = stamp
    record["updated_at"] = stamp
    record["version"] = 1
    record["_seq"] = next(db._seq)
    collection[record["id"]] = record
    return record


def touch(record):
    """A mutation (including one driven by a cascade) refreshes updated_at and
    bumps version by exactly 1 (PRD section 2.4 / 2.9)."""
    record["updated_at"] = wall_now()
    record["version"] = record["version"] + 1
    return record


def by_created(records):
    """created_at ascending, with insertion order as the deterministic tie-break."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def values(collection):
    return by_created(list(collection.values()))
