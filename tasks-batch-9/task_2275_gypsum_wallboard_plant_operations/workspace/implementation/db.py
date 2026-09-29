"""In-memory data store. Starts completely empty on every process boot: nothing
is seeded, preloaded or hardcoded here."""

from datetime import datetime, timezone

from util import fmt_dt, new_id, now_utc

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK_EPOCH_RAW = "2026-08-01T00:00:00Z"


class Store(object):
    def __init__(self):
        self.plants = {}
        self.board_lines = {}
        self.product_specs = {}
        self.markets = {}
        self.gypsum_lots = {}
        self.calciner_batches = {}
        self.batch_feeds = {}
        self.stucco_tests = {}
        self.production_runs = {}
        self.board_tests = {}
        self.maintenance_outages = {}
        self.load_orders = {}
        self._seq = 0
        self.clock = CLOCK_EPOCH
        self.clock_raw = CLOCK_EPOCH_RAW

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """The logical plant clock (PRD 2.6). Never falls back to wall time."""
        return self.clock


db = Store()


def base_entity(versioned=True):
    stamp = fmt_dt(now_utc())
    entity = {"id": new_id(), "created_at": stamp}
    if versioned:
        entity["updated_at"] = stamp
        entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def bump(entity):
    """A mutation of a versioned resource (PRD 2.4)."""
    entity["updated_at"] = fmt_dt(now_utc())
    entity["version"] = entity.get("version", 0) + 1
    return entity


def ordered(collection):
    """All rows of a collection sorted by created_at ascending (PRD 2.3)."""
    return sorted(collection.values(), key=lambda e: (e["created_at"], e["_seq"]))
