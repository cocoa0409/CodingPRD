"""In-memory data store, logical clock, and id/timestamp helpers.

The store starts completely empty on every boot — no seeding of any kind.
"""
import threading
import uuid
from datetime import datetime, timedelta, timezone

LOCK = threading.RLock()

STORE = {
    "aircraft": {},
    "lessees": {},
    "inspectors": {},
    "leases": {},
    "utilization_reports": {},
    "reserve_claims": {},
    "aircraft_documents": {},
    "return_cases": {},
    "checklist_items": {},
    "inspection_bookings": {},
    "novation_requests": {},
    "default_cases": {},
    "transition_slots": {},
}


# ---------------------------------------------------------------------------
# Wall-clock timestamps (created_at / updated_at / request meta). Guaranteed
# unique and monotonically increasing so created_at ASC ordering is stable.
# ---------------------------------------------------------------------------
_last_ts = None
_ts_lock = threading.Lock()


def now_iso():
    global _last_ts
    with _ts_lock:
        n = datetime.now(timezone.utc)
        if _last_ts is not None and n <= _last_ts:
            n = _last_ts + timedelta(milliseconds=1)
        _last_ts = n
    return "%s.%03dZ" % (n.strftime("%Y-%m-%dT%H:%M:%S"), n.microsecond // 1000)


# ---------------------------------------------------------------------------
# Logical clock: startup default exactly 2026-08-01T00:00:00Z, never falls
# back to wall-clock. All date-dependent business rules read this clock.
# ---------------------------------------------------------------------------
class LogicalClock:
    def __init__(self):
        self._dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._dt

    def set(self, dt):
        self._dt = dt

    def date_str(self):
        return self._dt.strftime("%Y-%m-%d")


CLOCK = LogicalClock()


def fmt_clock(dt):
    """Canonical ISO-8601 UTC rendering of a logical-clock instant."""
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += ".%06d" % dt.microsecond
    return base + "Z"


def new_id():
    return str(uuid.uuid4())


def base_entity(with_version=True):
    """Common fields. InspectionBooking passes with_version=False: it carries
    id and created_at only (no updated_at, no version)."""
    e = {"id": new_id(), "created_at": now_iso()}
    if with_version:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
    return e


def touch(e):
    e["updated_at"] = now_iso()
    e["version"] += 1
