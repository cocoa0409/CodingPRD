"""In-memory store plus the logical clock.

Nothing is seeded: every collection starts empty on every boot and all state is
created by clients through the declared endpoints.
"""
import datetime
import threading
import uuid
from decimal import Decimal

from util import UTC, fmt_ts

# The logical clock starts at exactly this instant on every boot (PRD 2.4).
CLOCK_EPOCH = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "plants",
    "cell_designs",
    "workers",
    "exposure_samples",
    "formation_bays",
    "test_chambers",
    "production_lots",
    "battery_assemblies",
    "formation_runs",
    "capacity_tests",
    "chargers",
    "fleet_sizing_requests",
    "battery_units",
    "maintenance_logs",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._clock = CLOCK_EPOCH
        self._seq = 0

    # ---- logical clock -------------------------------------------------
    def now(self):
        return self._clock

    def set_clock(self, moment):
        self._clock = moment

    # ---- identifiers ---------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    # ---- record lifecycle ----------------------------------------------
    def insert(self, collection, record, versioned=True):
        now = self.now()
        record["id"] = self.new_id()
        record["created_at"] = now
        if versioned:
            record["updated_at"] = now
            record["version"] = 1
        record["_seq"] = self.next_seq()
        getattr(self, collection)[record["id"]] = record
        return record

    def touch(self, record, bump=True):
        """Mark a row mutated: refresh updated_at and increment version.

        A row mutated several times inside one request advances its version by
        exactly 1 — cascades and the write that triggered them are one write.
        """
        if "updated_at" not in record and "version" not in record:
            return record
        record["updated_at"] = self.now()
        if not bump:
            return record
        if _already_touched(record):
            return record
        record["version"] = record.get("version", 1) + 1
        return record

    def rows(self, collection):
        return list(getattr(self, collection).values())


def _already_touched(record):
    """True when this row has already been version-bumped in this request."""
    try:
        from flask import g, has_request_context
    except ImportError:  # pragma: no cover
        return False
    if not has_request_context():
        return False
    seen = getattr(g, "_touched_rows", None)
    if seen is None:
        seen = set()
        g._touched_rows = seen
    key = record.get("id")
    if key in seen:
        return True
    seen.add(key)
    return False


db = Store()


def serialize(value):
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [serialize(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime.datetime):
        return fmt_ts(value)
    return value


def public(record):
    """Entity projection: every declared field, internals stripped."""
    return serialize(record)
