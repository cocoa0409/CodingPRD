"""LookRequirement, HoldingArea, and RatioWaiver endpoints."""
from flask import Blueprint, request

from db import STORE, new_id, next_seq, wall_now
from domain import (
    LOOK_CATEGORIES,
    _base,
    area_occupancy,
    ser_area,
    ser_look,
    ser_waiver,
    touch,
)
from errors import (
    ApiError,
    ERR_CALL_INVALID_STATE,
    ERR_HOLDING_AREA_NOT_FOUND,
    ERR_LOOK_REQUIREMENT_NOT_FOUND,
    ERR_PRODUCTION_NOT_ACTIVE,
    ERR_RATIO_WAIVER_NOT_FOUND,
    ERR_VALIDATION,
    ERR_WAIVER_INVALID_STATE,
    ERR_WAIVER_REDUCTION_INVALID,
)
from middleware import ALL_ROLES, auth, body, opt_bool, req_enum, req_int, req_str
from response import ok_list, ok_obj, paginate
from routes_calls import get_call
from routes_productions import get_production

bp = Blueprint("planning", __name__)


# --- LookRequirement (immutable: id + created_at only) ----------------------

@bp.post("/central-casting/look-requirements")
def create_look_requirement():
    auth(["CastingDirector"])
    data = body()
    casting_call_id = req_str(data, "casting_call_id")
    call = get_call(casting_call_id)
    category = req_enum(data, "category", LOOK_CATEGORIES)
    description = req_str(data, "description")
    bump_amount = req_int(data, "bump_amount_cents", minimum=1)
    mandatory = opt_bool(data, "mandatory", default=False)
    production = get_production(call["production_id"])
    if production["status"] != "ACTIVE":
        raise ApiError(ERR_PRODUCTION_NOT_ACTIVE, 409, "Production must be ACTIVE")
    if call["status"] != "DRAFT":
        raise ApiError(
            ERR_CALL_INVALID_STATE, 409, "Look requirements may only be added while the call is DRAFT"
        )
    lr = {
        "id": new_id(),
        "created_at": wall_now(),
        "_seq": next_seq(),
        "casting_call_id": casting_call_id,
        "category": category,
        "description": description,
        "bump_amount_cents": bump_amount,
        "mandatory": mandatory,
    }
    STORE.look_requirements[lr["id"]] = lr
    return ok_obj(ser_look(lr), code=201)


@bp.get("/central-casting/look-requirements")
def list_look_requirements():
    auth(ALL_ROLES)
    rows = sorted(STORE.look_requirements.values(), key=lambda l: l["_seq"])
    casting_call_id = request.args.get("casting_call_id")
    category = request.args.get("category")
    if casting_call_id is not None:
        rows = [l for l in rows if l["casting_call_id"] == casting_call_id]
    if category is not None:
        rows = [l for l in rows if l["category"] == category]
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_look(l) for l in page], total, limit, offset)


@bp.get("/central-casting/look-requirements/<lid>")
def get_look_requirement(lid):
    auth(ALL_ROLES)
    lr = STORE.look_requirements.get(lid)
    if lr is None:
        raise ApiError(ERR_LOOK_REQUIREMENT_NOT_FOUND, 404, "Look requirement not found")
    return ok_obj(ser_look(lr))


# --- HoldingArea --------------------------------------------------------------

def get_area(aid):
    a = STORE.holding_areas.get(aid)
    if a is None:
        raise ApiError(ERR_HOLDING_AREA_NOT_FOUND, 404, "Holding area not found")
    return a


@bp.post("/central-casting/holding-areas")
def create_holding_area():
    auth(["CastingAssociate"])
    data = body()
    casting_call_id = req_str(data, "casting_call_id")
    call = get_call(casting_call_id)
    name = req_str(data, "name")
    capacity = req_int(data, "capacity", minimum=1)
    production = get_production(call["production_id"])
    if production["status"] != "ACTIVE":
        raise ApiError(ERR_PRODUCTION_NOT_ACTIVE, 409, "Production must be ACTIVE")
    if call["status"] not in ("PUBLISHED", "LOCKED"):
        raise ApiError(
            ERR_CALL_INVALID_STATE,
            409,
            "Holding areas require the call PUBLISHED or LOCKED",
        )
    a = _base()
    a.update({"casting_call_id": casting_call_id, "name": name, "capacity": capacity})
    STORE.holding_areas[a["id"]] = a
    return ok_obj(ser_area(a), code=201)


@bp.get("/central-casting/holding-areas")
def list_holding_areas():
    auth(ALL_ROLES)
    rows = sorted(STORE.holding_areas.values(), key=lambda a: a["_seq"])
    casting_call_id = request.args.get("casting_call_id")
    if casting_call_id is not None:
        rows = [a for a in rows if a["casting_call_id"] == casting_call_id]
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_area(a) for a in page], total, limit, offset)


@bp.get("/central-casting/holding-areas/<aid>")
def get_holding_area(aid):
    auth(ALL_ROLES)
    return ok_obj(ser_area(get_area(aid)))


# --- RatioWaiver ---------------------------------------------------------------

def get_waiver(wid):
    w = STORE.ratio_waivers.get(wid)
    if w is None:
        raise ApiError(ERR_RATIO_WAIVER_NOT_FOUND, 404, "Ratio waiver not found")
    return w


@bp.post("/central-casting/ratio-waivers")
def create_waiver():
    user_id, _ = auth(["CastingDirector"])
    data = body()
    casting_call_id = req_str(data, "casting_call_id")
    call = get_call(casting_call_id)
    reduction = req_int(data, "union_slot_reduction", minimum=0)
    justification = req_str(data, "justification")
    if call["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError(
            ERR_CALL_INVALID_STATE,
            409,
            "Ratio waivers require the call DRAFT or PUBLISHED",
        )
    if reduction > call["union_slots"]:
        raise ApiError(
            ERR_WAIVER_REDUCTION_INVALID,
            422,
            "union_slot_reduction exceeds the call's union_slots",
        )
    w = _base()
    w.update(
        {
            "casting_call_id": casting_call_id,
            "union_slot_reduction": reduction,
            "justification": justification,
            "requested_by_user_id": user_id,
            "decided_by_user_id": None,
            "status": "REQUESTED",
        }
    )
    STORE.ratio_waivers[w["id"]] = w
    return ok_obj(ser_waiver(w), code=201)


@bp.get("/central-casting/ratio-waivers")
def list_waivers():
    auth(ALL_ROLES)
    rows = sorted(STORE.ratio_waivers.values(), key=lambda w: w["_seq"])
    casting_call_id = request.args.get("casting_call_id")
    status = request.args.get("status")
    if casting_call_id is not None:
        rows = [w for w in rows if w["casting_call_id"] == casting_call_id]
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_waiver(w) for w in page], total, limit, offset)


@bp.get("/central-casting/ratio-waivers/<wid>")
def get_waiver_route(wid):
    auth(ALL_ROLES)
    return ok_obj(ser_waiver(get_waiver(wid)))


@bp.post("/central-casting/ratio-waivers/<wid>/approve")
def approve_waiver(wid):
    user_id, _ = auth(["UnionRepresentative"])
    w = get_waiver(wid)
    if w["status"] != "REQUESTED":
        raise ApiError(ERR_WAIVER_INVALID_STATE, 409, "Waiver is not REQUESTED")
    call = get_call(w["casting_call_id"])
    if call["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError(
            ERR_CALL_INVALID_STATE,
            409,
            "Waiver approval requires the call DRAFT or PUBLISHED",
        )
    other_approved = any(
        other["casting_call_id"] == w["casting_call_id"]
        and other["status"] == "APPROVED"
        and other["id"] != w["id"]
        for other in STORE.ratio_waivers.values()
    )
    if other_approved:
        raise ApiError(ERR_VALIDATION, 400, "Another APPROVED waiver already exists for this call")
    w["status"] = "APPROVED"
    w["decided_by_user_id"] = user_id
    call["approved_waiver_reduction"] = w["union_slot_reduction"]
    touch(call)
    touch(w)
    return ok_obj(ser_waiver(w))


@bp.post("/central-casting/ratio-waivers/<wid>/deny")
def deny_waiver(wid):
    user_id, _ = auth(["UnionRepresentative"])
    w = get_waiver(wid)
    if w["status"] != "REQUESTED":
        raise ApiError(ERR_WAIVER_INVALID_STATE, 409, "Waiver is not REQUESTED")
    w["status"] = "DENIED"
    w["decided_by_user_id"] = user_id
    touch(w)
    return ok_obj(ser_waiver(w))
