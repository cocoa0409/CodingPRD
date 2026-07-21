"""In-memory data store, logical clock, id / timestamp minting.

The store starts EMPTY on every boot. Nothing is seeded, preloaded, or
hardcoded here; every entity is created through the API surface by tests.
"""

import time
import uuid
from datetime import datetime, timezone, timedelta

UTC = timezone.utc

# --- Logical clock: default fixed instant, never wall-clock fallback ---
CLOCK_DEFAULT = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)


class _State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        # one dict per entity collection, insertion-ordered (id -> record)
        self.tours = {}
        self.group_leaders = {}
        self.departures = {}
        self.enrollments = {}
        self.payment_plans = {}
        self.payments = {}
        self.permission_forms = {}
        self.chaperones = {}
        self.rooming_assignments = {}
        self.suppliers = {}
        self.supplier_bookings = {}


DB = _State()

# --- Strictly monotonic ISO-8601 millisecond timestamps ---
_last_ms = 0


def now_iso():
    """Return a strictly-increasing ISO 8601 UTC timestamp with 3 fractional digits."""
    global _last_ms
    ms = int(time.time() * 1000)
    if ms <= _last_ms:
        ms = _last_ms + 1
    _last_ms = ms
    secs, msec = divmod(ms, 1000)
    dt = datetime.fromtimestamp(secs, tz=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".{:03d}Z".format(msec)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex


def iso_from_dt(dt):
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".{:03d}Z".format(dt.microsecond // 1000)


def fmt_clock(dt):
    return iso_from_dt(dt)


def base_fields():
    """Common system fields for a freshly created resource (version starts at 1)."""
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(rec):
    """Record a mutation: bump version and refresh updated_at."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


ONE_DAY = timedelta(days=1)
