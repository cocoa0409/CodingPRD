"""In-memory data store, logical clock and record bookkeeping.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded.  Every entity is created through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timezone

# PRD 2.10: the logical clock starts at exactly 2026-08-01T00:00:00Z and never
# falls back to wall-clock time.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOCK = threading.RLock()


class Store(object):
    """Every collection is a plain dict keyed by the resource id."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.loops = {}
        self.segments = {}
        self.fuel_contracts = {}
        self.assets = {}
        self.forecasts = {}
        self.plans = {}
        self.orders = {}
        self.rate_schedules = {}
        self.agreements = {}
        self.points = {}
        self.readings = {}
        self.invoices = {}
        self.work_orders = {}
        self.projects = {}
        self.clock = INITIAL_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 instant, normalising to UTC.  Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text == "":
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def now():
    return store.clock


def now_ts():
    return fmt_ts(store.clock)


def base_record(versioned=True):
    """Common fields.  PRD 2.5: id + created_at always; updated_at + version
    for every living entity (DispatchOrder and MeterReading are append-only)."""
    record = {"id": new_id(), "created_at": now_ts()}
    if versioned:
        record["updated_at"] = now_ts()
        record["version"] = 1
    record["_seq"] = store.next_seq()
    return record


def touch(record):
    """A mutation: refresh updated_at and advance version by 1."""
    record["updated_at"] = now_ts()
    record["version"] = record.get("version", 0) + 1


def creation_order(items):
    """List order default (PRD 2.3): created_at ascending, insertion-stable."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
