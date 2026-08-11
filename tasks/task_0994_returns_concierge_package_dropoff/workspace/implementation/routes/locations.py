"""DropoffLocation and LockerSlot endpoints."""

from flask import Blueprint, request

from db import store, stamp, touch
from errors import ApiError, invalid_state, already_terminal
from services import (
    LOCATION_KINDS, SIZE_CLASSES, ser_location, ser_slot, ser_order, get_or_404,
)
from util import require_roles, respond, body, req_str, req_enum, paginate

bp = Blueprint("locations", __name__)


def _own_location(uid, role, location_id):
    if role == "LocationOperator" and uid != location_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "LocationOperator may act only at its own location")


@bp.post("/dropoff-locations")
def create_location():
    require_roles("PlatformAdmin")
    b = body(required=True)
    loc = {
        "name": req_str(b, "name"),
        "kind": req_enum(b, "kind", LOCATION_KINDS),
        "postal_code": req_str(b, "postal_code"),
        "status": "ONBOARDING",
    }
    stamp(loc)
    store["locations"][loc["id"]] = loc
    return respond(ser_location(loc), 201)


@bp.get("/dropoff-locations/<lid>")
def get_location(lid):
    uid, role = require_roles("PlatformAdmin", "LocationOperator",
                              "SupportAgent", "CarrierDispatcher")
    _own_location(uid, role, lid)
    return respond(ser_location(get_or_404("locations", lid)))


@bp.post("/dropoff-locations/<lid>/activate")
def activate_location(lid):
    require_roles("PlatformAdmin")
    loc = get_or_404("locations", lid)
    if loc["status"] == "DECOMMISSIONED":
        already_terminal("Location is DECOMMISSIONED")
    if loc["status"] != "ONBOARDING":
        invalid_state("Only an ONBOARDING location can be activated")
    loc["status"] = "OPERATIONAL"
    touch(loc)
    return respond(ser_location(loc))


@bp.post("/dropoff-locations/<lid>/pause")
def pause_location(lid):
    uid, role = require_roles("PlatformAdmin", "LocationOperator")
    _own_location(uid, role, lid)
    loc = get_or_404("locations", lid)
    if loc["status"] == "DECOMMISSIONED":
        already_terminal("Location is DECOMMISSIONED")
    if loc["status"] != "OPERATIONAL":
        invalid_state("Only an OPERATIONAL location can be paused")
    loc["status"] = "PAUSED"
    touch(loc)
    return respond(ser_location(loc))


@bp.post("/dropoff-locations/<lid>/resume")
def resume_location(lid):
    uid, role = require_roles("PlatformAdmin", "LocationOperator")
    _own_location(uid, role, lid)
    loc = get_or_404("locations", lid)
    if loc["status"] == "DECOMMISSIONED":
        already_terminal("Location is DECOMMISSIONED")
    if loc["status"] != "PAUSED":
        invalid_state("Only a PAUSED location can be resumed")
    loc["status"] = "OPERATIONAL"
    touch(loc)
    return respond(ser_location(loc))


@bp.post("/dropoff-locations/<lid>/decommission")
def decommission_location(lid):
    require_roles("PlatformAdmin")
    loc = get_or_404("locations", lid)
    if loc["status"] == "DECOMMISSIONED":
        already_terminal("Location is DECOMMISSIONED")
    if loc["status"] not in ("OPERATIONAL", "PAUSED"):
        invalid_state("Only an OPERATIONAL or PAUSED location can be decommissioned")
    for s in store["slots"].values():
        if s["location_id"] == lid and s["status"] in ("RESERVED", "OCCUPIED"):
            raise ApiError("ERR_LOCATION_BUSY", 409,
                           "Decommission blocked: slot RESERVED or OCCUPIED")
    for s in store["slots"].values():
        if s["location_id"] == lid and s["status"] == "EMPTY":
            s["status"] = "OUT_OF_SERVICE"
            touch(s)
    loc["status"] = "DECOMMISSIONED"
    touch(loc)
    return respond(ser_location(loc))


@bp.get("/dropoff-locations/<lid>/locker-slots")
def list_slots(lid):
    uid, role = require_roles("PlatformAdmin", "LocationOperator",
                              "SupportAgent", "Shopper")
    _own_location(uid, role, lid)
    get_or_404("locations", lid)
    items = [s for s in store["slots"].values() if s["location_id"] == lid]
    size_class = request.args.get("size_class")
    status = request.args.get("status")
    if size_class is not None:
        items = [s for s in items if s["size_class"] == size_class]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items)
    return respond([ser_slot(s) for s in page], page=meta)


@bp.get("/dropoff-locations/<lid>/return-orders")
def list_location_orders(lid):
    uid, role = require_roles("PlatformAdmin", "LocationOperator", "SupportAgent")
    _own_location(uid, role, lid)
    get_or_404("locations", lid)
    items = [o for o in store["orders"].values()
             if o.get("dropoff_location_id") == lid]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, meta = paginate(items)
    return respond([ser_order(o) for o in page], page=meta)


@bp.post("/dropoff-locations/<lid>/locker-slots")
def create_slot(lid):
    require_roles("PlatformAdmin")
    get_or_404("locations", lid)
    b = body(required=True)
    slot = {
        "location_id": lid,
        "size_class": req_enum(b, "size_class", SIZE_CLASSES),
        "status": "EMPTY",
    }
    stamp(slot)
    store["slots"][slot["id"]] = slot
    return respond(ser_slot(slot), 201)


# ------------------------------------------------------------- locker slots -
@bp.get("/locker-slots/<sid>")
def get_slot(sid):
    uid, role = require_roles("PlatformAdmin", "LocationOperator", "SupportAgent")
    slot = get_or_404("slots", sid)
    _own_location(uid, role, slot["location_id"])
    return respond(ser_slot(slot))


@bp.post("/locker-slots/<sid>/out-of-service")
def slot_out_of_service(sid):
    uid, role = require_roles("LocationOperator", "PlatformAdmin")
    slot = get_or_404("slots", sid)
    _own_location(uid, role, slot["location_id"])
    if slot["status"] != "EMPTY":
        invalid_state("Only an EMPTY slot can be marked out of service")
    slot["status"] = "OUT_OF_SERVICE"
    touch(slot)
    return respond(ser_slot(slot))


@bp.post("/locker-slots/<sid>/restore")
def slot_restore(sid):
    uid, role = require_roles("LocationOperator", "PlatformAdmin")
    slot = get_or_404("slots", sid)
    _own_location(uid, role, slot["location_id"])
    if slot["status"] != "OUT_OF_SERVICE":
        invalid_state("Only an OUT_OF_SERVICE slot can be restored")
    slot["status"] = "EMPTY"
    touch(slot)
    return respond(ser_slot(slot))


@bp.post("/locker-slots/<sid>/sweep-collect")
def slot_sweep_collect(sid):
    uid, role = require_roles("LocationOperator")
    slot = get_or_404("slots", sid)
    _own_location(uid, role, slot["location_id"])
    if slot["status"] != "OCCUPIED":
        invalid_state("Only an OCCUPIED slot can be sweep-collected")
    slot["status"] = "EMPTY"
    touch(slot)
    return respond(ser_slot(slot))
