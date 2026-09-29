"""In-memory data store, id/timestamp minting and the plant logical clock.

The store starts EMPTY on every boot: no seeded, preloaded or hardcoded
entities.  Every entity a test needs is built through the declared API surface.
"""

import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone

# PRD §2.4 — mandatory logical-clock default before it has ever been set.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.lines = {}
        self.stations = {}
        self.model_variants = {}
        self.suppliers = {}
        self.parts = {}
        self.bom_lines = {}
        self.delivery_calls = {}
        self.shift_plans = {}
        self.build_slots = {}
        self.production_units = {}
        self.quality_tests = {}
        self.engineering_changes = {}
        self.warranty_returns = {}
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)
        self._last_ts = None

    def next_seq(self):
        return next(self._seq)

    def next_ts(self):
        """Strictly monotonic wall-clock timestamp (millisecond resolution).

        Monotonicity removes tie-breaking ambiguity from every `created_at`
        ordering the PRD relies on, and guarantees `updated_at >= created_at`.
        """
        now = datetime.now(timezone.utc).replace(microsecond=(datetime.now(timezone.utc).microsecond // 1000) * 1000)
        if self._last_ts is not None and now <= self._last_ts:
            now = self._last_ts + timedelta(milliseconds=1)
        self._last_ts = now
        return now


db = Store()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def new_record(versioned=True):
    ts = db.next_ts()
    rec = {"id": new_id(), "created_at": ts, "_seq": db.next_seq()}
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec, bump=True):
    """Refresh updated_at and (optionally) advance the record's version."""
    if rec is None:
        return
    rec["updated_at"] = db.next_ts()
    if bump and "version" in rec:
        rec["version"] = rec["version"] + 1


def clock():
    return db.clock
