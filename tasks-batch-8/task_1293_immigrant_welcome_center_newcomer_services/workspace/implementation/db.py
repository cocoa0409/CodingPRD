"""In-memory data store. Starts empty on every boot — no seeding."""
import threading
from datetime import datetime

from util import fmt_iso, new_id, CLOCK

LOCK = threading.RLock()

# collection name -> {id: entity-dict}
STORE = {
    "clients": {},
    "staff": {},
    "organizations": {},
    "rooms": {},
    "cases": {},
    "assessments": {},
    "plans": {},
    "notes": {},
    "consents": {},
    "referrals": {},
    "appointments": {},
    "programs": {},
    "enrollments": {},
    "sessions": {},
    "wk_enrollments": {},
    "screenings": {},
    "reports": {},
}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def now():
    return CLOCK.now()


def new_entity(collection, fields, common=True):
    """Create, store and return a new entity dict."""
    ent = {"id": new_id(), "_seq": next_seq()}
    ent.update(fields)
    ts = now()
    ent["created_at"] = ts
    if common:
        ent["updated_at"] = ts
        ent["version"] = 1
    STORE[collection][ent["id"]] = ent
    return ent


def touch(ent):
    """Refresh updated_at and bump version on a mutation."""
    ent["updated_at"] = now()
    ent["version"] = ent.get("version", 0) + 1


def get(collection, entity_id):
    return STORE[collection].get(entity_id)


def all_of(collection):
    return sorted(STORE[collection].values(),
                  key=lambda e: (e["created_at"], e["_seq"]))


def find(collection, **filters):
    return [e for e in all_of(collection)
            if all(e.get(k) == v for k, v in filters.items())]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def serialize(value):
    """Recursively convert datetimes to canonical strings for JSON output."""
    if isinstance(value, datetime):
        return fmt_iso(value)
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    return value


def pub(ent):
    """Public view of an entity: strip internal keys, convert datetimes."""
    return {k: serialize(v) for k, v in ent.items() if not k.startswith("_")}
