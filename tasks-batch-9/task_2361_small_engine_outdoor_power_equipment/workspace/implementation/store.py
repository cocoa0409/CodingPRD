"""In-memory data store and the server-held logical plant clock.

Storage is process-local Python dictionaries only.  The store is EMPTY on every
boot: nothing is seeded, preloaded or hardcoded here or anywhere else.
"""

import itertools
import uuid
from datetime import datetime, timezone


# PRD 2.4 — before any request is made the logical clock reads exactly this.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def iso_millis(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_clock(dt):
    """Canonical rendering of a logical-clock instant.

    Whole-second instants render without a fractional part, mirroring the form
    in which the clock is positioned; sub-second instants keep three digits.
    """
    if dt.microsecond == 0:
        return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        )
    return iso_millis(dt)


class DB(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = INITIAL_CLOCK
        self._seq = itertools.count(1)
        self.families = {}
        self.platforms = {}
        self.durability_tests = {}
        self.product_models = {}
        self.safety_certifications = {}
        self.suppliers = {}
        self.component_lots = {}
        self.machining_runs = {}
        self.assembly_lines = {}
        self.build_orders = {}
        self.engine_units = {}
        self.line_audits = {}
        self.service_parts = {}
        self.parts_requests = {}

    def seq(self):
        return next(self._seq)


db = DB()


def now():
    return db.clock


def now_millis():
    return iso_millis(db.clock)


def now_clock():
    return iso_clock(db.clock)


def clock_date():
    return db.clock.date()


def new_record(fields, versioned=True):
    """Build a record dict.  `fields` is an ordered mapping of entity fields."""
    rec = {"id": str(uuid.uuid4())}
    rec.update(fields)
    rec["created_at"] = now_millis()
    if versioned:
        rec["updated_at"] = now_millis()
        rec["version"] = 1
    rec["_seq"] = db.seq()
    return rec


def bump(rec):
    """Unconditionally mark a row as mutated."""
    rec["updated_at"] = now_millis()
    rec["version"] = rec.get("version", 1) + 1


def set_fields(rec, **changes):
    """Apply changes; refresh updated_at / version once when anything differs."""
    changed = False
    for key, value in changes.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    if changed:
        bump(rec)
    return changed


def sort_created_asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}
