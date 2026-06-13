"""In-memory data store. Starts EMPTY on every process boot — no seeding."""
import itertools
import uuid

from response import now_iso

# One dict per entity collection, keyed by id. All empty at startup.
stylists = {}
fitting_rooms = {}
bridal_parties = {}
appointments = {}
fitting_room_bookings = {}
gown_orders = {}
accessory_addons = {}
alteration_jobs = {}
payment_plans = {}
payments = {}

# Monotonic sequence for stable creation-order sorting (PRD §2.3: ascending by
# creation timestamp). Millisecond timestamps can collide within a single test,
# so an internal sequence breaks ties deterministically in creation order.
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def stamp_create(obj, with_version=True):
    """Attach common system fields on creation (PRD §2.4)."""
    ts = now_iso()
    obj["created_at"] = ts
    obj["_seq"] = next_seq()
    if with_version:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    """Refresh updated_at and bump version on any mutation (PRD §2.4)."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
