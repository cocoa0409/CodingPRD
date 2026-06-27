"""In-memory data store. All state is held in plain Python dicts keyed by id.

Storage is in-memory ONLY: no SQLite, no JSON file, no /tmp cache. Every
per-test-server restart re-imports this module fresh and wipes all state.
No entities are seeded or preloaded at startup — tests build all preconditions
via the declared API surface.
"""
import itertools
import uuid

from clock import clock, format_iso8601_ms


class Store:
    def __init__(self):
        # one dict per first-class entity, keyed by id (UUID string)
        self.units = {}
        self.floor_plan_notes = {}
        self.customers = {}
        self.trade_ins = {}
        self.deals = {}
        self.auction_lots = {}
        self.bids = {}
        self.work_orders = {}
        self.part_lines = {}
        self.parts = {}
        self.warranty_claims = {}
        self.whole_goods_orders = {}
        # monotonic sequence to break created_at ties deterministically
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Creation/mutation timestamps follow the logical clock is NOT used here;
    common-field timestamps are server time. PRD §2.4 says created_at/updated_at
    are ISO 8601 UTC with three fractional digits. We use wall-clock time for
    these audit timestamps (the logical clock governs business time only)."""
    from datetime import datetime, timezone
    return format_iso8601_ms(datetime.now(timezone.utc))


def make_common(entity):
    """Stamp id, created_at, updated_at, version onto a first-class resource."""
    entity["id"] = new_id()
    entity["created_at"] = now_ts()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Refresh updated_at and bump version on every mutation (PRD §2.5)."""
    entity["updated_at"] = now_ts()
    entity["version"] = entity.get("version", 1) + 1
