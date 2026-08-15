"""Field closure routes: create (with rain-out cascade), list, read, lift (PRD 3.7)."""

from flask import Blueprint, request

import errors
import util
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object
from services import core

bp = Blueprint("closures", __name__)

CLOSURE_REASONS = ("RAIN", "TURF_REST", "MAINTENANCE", "SAFETY")


@bp.post("/field-closures")
def create_closure():
    require_roles("FieldSupervisor")
    body = util.get_json_body()
    facility_id = util.require_str(body, "facility_id")
    closure_date = util.require_date(body, "closure_date")
    reason = util.require_enum(body, "reason", CLOSURE_REASONS)

    has_start = body.get("start_minute") is not None
    has_end = body.get("end_minute") is not None
    if has_start != has_end:
        raise errors.ApiError(errors.ERR_INVALID_TIME_RANGE,
                              "start_minute and end_minute must both be present or both omitted", 409)
    if has_start:
        start_minute = util.require_int(body, "start_minute", min_v=0, max_v=1439)
        end_minute = util.require_int(body, "end_minute", min_v=1, max_v=1440)
        if end_minute <= start_minute:
            raise errors.ApiError(errors.ERR_INVALID_TIME_RANGE,
                                  "end_minute must be strictly after start_minute", 409)
    else:
        start_minute = None
        end_minute = None

    facility = core.get_facility(facility_id)

    closure = util.new_entity({
        "facility_id": facility["id"],
        "closure_date": closure_date.strftime("%Y-%m-%d"),
        "start_minute": start_minute,
        "end_minute": end_minute,
        "reason": reason,
        "status": "ACTIVE",
    })
    store.field_closures[closure["id"]] = closure

    # Rain-out cascade: every RESERVED/CONFIRMED permit on facility+date whose
    # slot intersects the closure (any slot for a full-day closure).
    for p in sorted(store.permits.values(), key=util.sort_key):
        if p["status"] not in ("RESERVED", "CONFIRMED"):
            continue
        if core.closure_intersects_permit(closure, p):
            core.rain_out_permit(p)

    return success_object(closure, 201)


@bp.get("/field-closures")
def list_closures():
    require_roles(*ANY_ROLE)
    items = list(store.field_closures.values())
    for param in ("facility_id", "closure_date", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [c for c in items if c.get(param) == val]
    return util.paginate(items)


@bp.get("/field-closures/<cid>")
def get_closure(cid):
    require_roles(*ANY_ROLE)
    return success_object(core.get_closure(cid))


@bp.post("/field-closures/<cid>/lift")
def lift_closure(cid):
    require_roles("FieldSupervisor")
    closure = core.get_closure(cid)
    if closure["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_INVALID_CLOSURE_STATE,
                              "Closure is already LIFTED", 409)
    closure["status"] = "LIFTED"
    util.touch(closure)
    # One-way cascade: RAINED_OUT permits are NOT reverted (PRD 3.7).
    return success_object(closure)
