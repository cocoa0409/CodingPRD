"""In-memory data store, logical clock and record bookkeeping.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded here.  Every row is created through the declared API.
"""

import datetime
import itertools
import uuid

from envelope import iso_ms

UTC = datetime.timezone.utc

# The logical production clock reads exactly this instant before any client
# touches it, and never falls back to real wall-clock time (PRD 2.5).
CLOCK_DEFAULT = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.varieties = {}
        self.treatment_products = {}
        self.growers = {}
        self.production_fields = {}
        self.field_history_records = {}
        self.production_contracts = {}
        self.field_inspections = {}
        self.harvest_equipment = {}
        self.harvest_events = {}
        self.conditioning_lines = {}
        self.seed_lots = {}
        self.conditioning_runs = {}
        self.lot_samples = {}
        self.certification_tags = {}
        self.settlements = {}
        self.clock = CLOCK_DEFAULT
        self.clock_raw = None
        self._seq = itertools.count(1)
        self._tag_seq = itertools.count(1)

    # ---- clock -----------------------------------------------------------
    def now(self):
        return self.clock

    def today(self):
        return self.clock.date()

    def set_clock(self, dt, raw):
        self.clock = dt
        self.clock_raw = raw

    # ---- sequences -------------------------------------------------------
    def next_seq(self):
        return next(self._seq)

    def next_tag_seq(self):
        return next(self._tag_seq)


db = Store()


def new_record(common_fields=True):
    """Fresh row with id/created_at (+ updated_at/version when applicable)."""
    stamp = iso_ms(datetime.datetime.now(UTC))
    rec = {"id": str(uuid.uuid4()), "created_at": stamp, "_seq": db.next_seq()}
    if common_fields:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at and bump version by one."""
    if "version" in rec:
        rec["version"] = rec["version"] + 1
        rec["updated_at"] = iso_ms(datetime.datetime.now(UTC))
    return rec


def by_created_at(rows):
    """created_at ascending, with insertion order as the stable tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
