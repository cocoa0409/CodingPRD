"""In-memory data store and the settable logical clock (PRD §2.4).

The store starts completely empty on every boot; nothing is seeded.
"""
import itertools
import uuid
from datetime import datetime, timezone

from errors import fail
from response import iso_now

# --------------------------------------------------------------- collections
centers = {}
berths = {}
vessels = {}
vehicles = {}
surveys = {}
claims = {}
repair_orders = {}
kits = {}
work_orders = {}
inspections = {}
hold_orders = {}
dealers = {}
carriers = {}
release_orders = {}

_seq = itertools.count(1)

# ------------------------------------------------------------- logical clock
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"current_utc": CLOCK_DEFAULT}


def clock_now():
    return _clock["current_utc"]


def clock_set(dt):
    _clock["current_utc"] = dt
    return dt


# ------------------------------------------------------------------ plumbing
def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    """Common fields: id + created_at, plus updated_at/version unless immutable."""
    rec = {"id": new_id(), "created_at": iso_now(), "_seq": next(_seq)}
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Record a mutation: refresh updated_at and increment version."""
    if "version" in rec:
        rec["updated_at"] = iso_now()
        rec["version"] = rec["version"] + 1
    return rec


def ordered(store):
    """All records of a collection in created_at ascending order."""
    return sorted(store.values(), key=lambda r: r["_seq"])


_NOT_FOUND = {
    "centers": "ERR_CENTER_NOT_FOUND",
    "berths": "ERR_BERTH_NOT_FOUND",
    "vessels": "ERR_VESSEL_NOT_FOUND",
    "vehicles": "ERR_VEHICLE_NOT_FOUND",
    "surveys": "ERR_SURVEY_NOT_FOUND",
    "claims": "ERR_CLAIM_NOT_FOUND",
    "repair_orders": "ERR_REPAIR_ORDER_NOT_FOUND",
    "kits": "ERR_KIT_NOT_FOUND",
    "work_orders": "ERR_WORK_ORDER_NOT_FOUND",
    "inspections": "ERR_INSPECTION_NOT_FOUND",
    "hold_orders": "ERR_HOLD_ORDER_NOT_FOUND",
    "dealers": "ERR_DEALER_NOT_FOUND",
    "carriers": "ERR_CARRIER_NOT_FOUND",
    "release_orders": "ERR_RELEASE_ORDER_NOT_FOUND",
}

_STORES = {
    "centers": centers,
    "berths": berths,
    "vessels": vessels,
    "vehicles": vehicles,
    "surveys": surveys,
    "claims": claims,
    "repair_orders": repair_orders,
    "kits": kits,
    "work_orders": work_orders,
    "inspections": inspections,
    "hold_orders": hold_orders,
    "dealers": dealers,
    "carriers": carriers,
    "release_orders": release_orders,
}


def must_get(name, resource_id):
    """Resolve a path identifier or raise the collection's dedicated 404."""
    rec = _STORES[name].get(resource_id)
    if rec is None:
        fail(_NOT_FOUND[name], "%s does not resolve" % (resource_id,))
    return rec
