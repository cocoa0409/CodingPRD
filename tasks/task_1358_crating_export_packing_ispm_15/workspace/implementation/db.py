"""In-memory data store + logical clock (PRD §2.4, §2.5).

The store starts EMPTY on every boot. No seeding of any kind.
"""
import uuid
from datetime import datetime, timezone

STORE = {
    "customers": {},
    "jobs": {},
    "items": {},
    "designs": {},
    "batches": {},
    "crates": {},
    "declarations": {},
    "packing_lists": {},
    "invoices": {},
    "crews": {},
    "bookings": {},
    "permits": {},
    "containers": {},
    "claims": {},
}

# Logical clock: starts at exactly 2026-08-01T00:00:00Z, never wall-clock.
_LOGICAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def logical_now():
    return _LOGICAL_CLOCK


def set_logical_clock(dt):
    global _LOGICAL_CLOCK
    _LOGICAL_CLOCK = dt


def new_id():
    return str(uuid.uuid4())


def wall_now():
    return datetime.now(timezone.utc)


def iso_ms(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso_ms(wall_now())


def touch(record):
    """Bump version and refresh updated_at (PRD §2.4: every modification)."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now_iso()
