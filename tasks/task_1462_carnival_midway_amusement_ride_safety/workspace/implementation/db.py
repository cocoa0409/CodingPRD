"""In-memory data store, logical clock, and entity mutation helpers.

Storage is process-local dicts keyed by id. Every boot starts completely
empty: no seeding, no disk persistence, no caches. The logical clock starts
at exactly 2026-08-01T00:00:00Z and only moves via POST /midway/_clock/set_current_utc.
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": CLOCK_START}


def clock_now():
    return _clock["now"]


def clock_set(dt):
    _clock["now"] = dt


def today_date():
    """Current logical date as a date object."""
    return clock_now().date()


def today_str():
    return clock_now().strftime("%Y-%m-%d")


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_ts(clock_now())


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
store = {
    "fairs": {},
    "rides": {},
    "inspectors": {},
    "appointments": {},
    "permits": {},
    "staff": {},
    "certifications": {},
    "operating_days": {},
    "checklists": {},
    "cycles": {},
    "redemptions": {},
    "products": {},
    "sales": {},
    "observations": {},
    "incidents": {},
    "shifts": {},
}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def register(collection, entity):
    """Insert a new entity, stamping system-managed fields."""
    entity["id"] = new_id()
    entity["_seq"] = next_seq()
    ts = now_iso()
    entity["created_at"] = ts
    if collection != "observations":  # WeatherObservation is append-only: no updated_at/version
        entity["updated_at"] = ts
        entity["version"] = 1
    store[collection][entity["id"]] = entity
    return entity


def touch(entity):
    """Mark an entity as mutated by the current request: version +1, updated_at refreshed.

    Deduplicated per request so a cascade touching one entity through several
    code paths advances its version exactly once per request.
    """
    if entity is None or "version" not in entity:
        return
    from flask import g

    if not hasattr(g, "_touched"):
        g._touched = set()
    key = id(entity)
    if key in g._touched:
        return
    g._touched.add(key)
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def serialize(entity):
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_key(entity):
    return (entity["created_at"], entity["_seq"])


def find_by(collection, **filters):
    return [
        e
        for e in store[collection].values()
        if all(e.get(k) == v for k, v in filters.items())
    ]


def get(collection, entity_id):
    return store[collection].get(entity_id)
