"""In-memory data store and the logical clock.

Storage is plain Python dicts keyed by entity id. The store starts empty on
every boot; nothing is seeded. The logical clock defaults to exactly
2026-08-01T00:00:00Z at startup and is advanced only through the
/recycle-routes/_clock/set_current_utc endpoint. Every "now" the server needs
(created_at, updated_at, installed_at, screening_recorded_at, the request
timestamp, the manifest scheduled-date rule, the facility daily aggregation)
reads this logical clock and never the wall clock.
"""

import threading
import uuid
from datetime import datetime, timezone

_lock = threading.RLock()

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock_now = _DEFAULT_CLOCK


def now():
    """Current logical time (UTC-aware datetime)."""
    with _lock:
        return _clock_now


def today_iso():
    """Current logical calendar date as YYYY-MM-DD."""
    return now().date().isoformat()


def set_clock(dt):
    global _clock_now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    with _lock:
        _clock_now = dt
    return _clock_now


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_ts(now())


# ---------------------------------------------------------------------------
# Entity stores
# ---------------------------------------------------------------------------

stores = {
    "customers": {},
    "tank_sites": {},
    "tanks": {},
    "drivers": {},
    "routes": {},
    "route_stops": {},
    "sample_screenings": {},
    "pickup_tickets": {},
    "manifests": {},
    "disposal_facilities": {},
    "blend_batches": {},
    "market_prices": {},
    "spill_incidents": {},
}

# Global monotonic creation sequence: stable tiebreak when several resources
# share the same logical created_at (the logical clock may not move between
# creations). Never serialized.
_seq_counter = [0]


def _next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def new_id():
    return str(uuid.uuid4())


def create_entity(store_name, fields, common=True):
    """Insert a new entity. System fields: id, created_at, updated_at, version."""
    ts = now_iso()
    entity = dict(fields)
    entity["id"] = new_id()
    entity["created_at"] = ts
    if common:
        entity["updated_at"] = ts
        entity["version"] = 1
    entity["_seq"] = _next_seq()
    with _lock:
        stores[store_name][entity["id"]] = entity
    return entity


def touch(entity):
    """Mark a mutation: refresh updated_at and bump version (OCC field)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def get(store_name, entity_id):
    return stores[store_name].get(entity_id)


def all_entities(store_name):
    return list(stores[store_name].values())


def serialize(entity):
    """Public view of an entity: strip internal underscore-prefixed keys."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sorted_created(entities):
    """Default list ordering: created_at ascending, insertion order on ties."""
    return sorted(entities, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
