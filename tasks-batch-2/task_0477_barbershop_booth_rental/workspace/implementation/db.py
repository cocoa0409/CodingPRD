"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid
from datetime import datetime, timezone

# One dict per entity collection, keyed by id.
shops = {}
barbers = {}
chairs = {}
shifts = {}
services = {}
addons = {}
products = {}
memberships = {}
customers = {}
appointments = {}
queue_tickets = {}
tickets = {}
settlements = {}

# Monotonic creation sequence so created_at ties are broken deterministically.
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock-independent creation timestamp (real time, 3 fractional digits).

    created_at/updated_at are server clock stamps; the *logical* clock (clock.py)
    governs business rules. These are distinct concerns per PRD §2.4 / §2.5.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def stamp_create(obj):
    ts = now_iso()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next(_seq)
    return obj


def touch(obj):
    """Refresh updated_at and bump version on any mutation."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj


# Public (serializable) field projection: hide internal bookkeeping keys.
_HIDDEN = {"_seq"}


def public(obj):
    return {k: v for k, v in obj.items() if k not in _HIDDEN}
