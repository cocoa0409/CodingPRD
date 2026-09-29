"""In-memory data store.

Every collection starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded here -- every entity is created through the public API surface.
"""
import threading
import time
import uuid
from datetime import datetime, timezone

# Logical clock start-up position (PRD 2.6).
CLOCK_DEFAULT_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"

lock = threading.RLock()


class Store(object):
    def __init__(self):
        self.branches = {}
        self.jurisdictions = {}
        self.building_specs = {}
        self.configs = {}
        self.units = {}
        self.customers = {}
        self.leases = {}
        self.accessory_packages = {}
        self.permits = {}
        self.jobs = {}
        self.assessments = {}
        self.line_items = {}
        self.refurb_orders = {}
        self.clock_dt = CLOCK_DEFAULT_DT
        self.clock_raw = CLOCK_DEFAULT_RAW
        self._last_ms = 0
        self._seq = 0


store = Store()


def _next_ms():
    ms = int(time.time() * 1000)
    if ms <= store._last_ms:
        ms = store._last_ms + 1
    store._last_ms = ms
    return ms


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    ms = _next_ms()
    dt = datetime.fromtimestamp(ms // 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (ms % 1000)


def next_seq():
    store._seq += 1
    return store._seq


def new_id():
    return str(uuid.uuid4())


def new_record(**fields):
    """Create a record carrying the four common system properties."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(fields)
    return rec


def new_append_only(**fields):
    """DamageLineItem: only id + created_at (PRD 2.4)."""
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """A write to a resource moves updated_at and bumps version by one."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 0) + 1
    return rec


def ordered(collection):
    """Every list is sorted by creation timestamp ascending (PRD 2.3)."""
    return sorted(collection, key=lambda r: r["_seq"])


def clock_date():
    return store.clock_dt.date()
