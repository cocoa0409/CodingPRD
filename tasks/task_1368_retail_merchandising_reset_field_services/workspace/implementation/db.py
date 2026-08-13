"""In-memory data store and server-managed logical clock.

Storage is plain Python dicts keyed by id. The store starts empty on every
boot -- nothing is seeded or preloaded. The logical clock defaults to
2026-08-01T00:00:00Z and is only advanced via POST /_clock/set_current_utc;
it never falls back to wall-clock time.
"""
import threading
import uuid
from datetime import datetime, timezone

_lock = threading.RLock()

# Entity collections, keyed by id. Values are plain dicts; keys starting
# with "_" are internal bookkeeping and stripped at serialization time.
collections = {
    "clients": {},
    "stores": {},
    "reps": {},
    "projects": {},
    "project_stores": {},
    "assignments": {},
    "store_visits": {},
    "photos": {},
    "exceptions": {},
    "shipments": {},
    "rework_auths": {},
    "mileage_logs": {},
    "invoices": {},
}

_seq = 0
# Logical clock: exactly 2026-08-01T00:00:00Z before any clock-setting call.
_clock_now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def next_seq():
    global _seq
    with _lock:
        _seq += 1
        return _seq


def now():
    """Current logical-clock instant (aware, UTC)."""
    return _clock_now


def set_clock(dt):
    global _clock_now
    _clock_now = dt


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def base_fields():
    """Common system fields for primary resources (id/created_at/updated_at/version)."""
    ts = fmt_ts(_clock_now)
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def light_fields():
    """Common fields for immutable evidence resources (id/created_at only)."""
    return {
        "id": new_id(),
        "created_at": fmt_ts(_clock_now),
        "_seq": next_seq(),
    }


def touch(entity):
    """Record a modification: version += 1 and updated_at refreshed."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = fmt_ts(_clock_now)


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_list(entities):
    return [serialize(e) for e in entities]


def sorted_by_creation(items):
    return sorted(items, key=lambda e: e["_seq"])
