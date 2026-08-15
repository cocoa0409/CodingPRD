from decimal import Decimal

from flask import Blueprint, request

from auth import require
from domain import (dump_coman, dump_agreement, dump_slot, get_coman, get_product,
                    get_agreement, get_slot)
from errors import ApiError
from store import STORE, new_entity, touch, sort_key
from util import body, ok, paginate, req_str, req_num, req_int, opt_bool, parse_date, D, rhu

bp = Blueprint("coman", __name__)

COMAN_RW = ["PlantManager", "CoManufacturer"]


@bp.post("/snack-mfg/co-manufacturers")
def create_coman():
    require(["PlantManager"])
    data = body()
    name = req_str(data, "name")
    active = opt_bool(data, "active", default=True)
    for other in STORE.comans.values():
        if other["name"] == name:
            raise ApiError("ERR_VALIDATION", 400, "co-manufacturer name must be unique")
    cm = new_entity(STORE)
    cm.update({"name": name, "active": active})
    STORE.comans[cm["id"]] = cm
    return ok(STORE, dump_coman(cm), status=201)


@bp.get("/snack-mfg/co-manufacturers/<cid>")
def get_coman_ep(cid):
    require(None)
    cm = get_coman(STORE, cid)
    return ok(STORE, dump_coman(cm))


@bp.post("/snack-mfg/co-man-agreements")
def create_agreement():
    require(["PlantManager"])
    data = body()
    coman_id = data.get("co_manufacturer_id")
    coman = get_coman(STORE, coman_id) if isinstance(coman_id, str) else None
    if coman is None:
        if not isinstance(coman_id, str) or coman_id == "":
            raise ApiError("ERR_VALIDATION", 400, "missing or invalid field: co_manufacturer_id")
        raise ApiError("ERR_COMAN_NOT_FOUND", 404, "co-manufacturer not found")
    weekly_capacity = req_num(data, "weekly_capacity_lbs", gt=0)
    rate = req_int(data, "rate_per_lb_cents", ge=0)
    budget = req_int(data, "budget_cents", ge=0)
    a = new_entity(STORE)
    a.update({
        "co_manufacturer_id": coman["id"], "weekly_capacity_lbs": weekly_capacity,
        "rate_per_lb_cents": rate, "budget_cents": budget, "status": "DRAFT",
    })
    STORE.agreements[a["id"]] = a
    return ok(STORE, dump_agreement(a), status=201)


def _own_agreement_or_forbid(agreement, uid, role):
    """Validation tier 4: CoManufacturer ownership scope."""
    if role == "CoManufacturer" and agreement["co_manufacturer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "agreement is not owned by this co-manufacturer")


@bp.get("/snack-mfg/co-man-agreements/<aid>")
def get_agreement_ep(aid):
    uid, role = require(COMAN_RW)
    a = get_agreement(STORE, aid)
    _own_agreement_or_forbid(a, uid, role)
    return ok(STORE, dump_agreement(a))


@bp.get("/snack-mfg/co-man-agreements")
def list_agreements():
    uid, role = require(COMAN_RW)
    items = list(STORE.agreements.values())
    if role == "CoManufacturer":
        items = [a for a in items if a["co_manufacturer_id"] == uid]
    else:
        coman_id = request.args.get("co_manufacturer_id")
        if coman_id is not None:
            items = [a for a in items if a["co_manufacturer_id"] == coman_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=sort_key)
    page, meta = paginate([dump_agreement(a) for a in items])
    return ok(STORE, page, response_type="array", pagination=meta)


def _agreement_terminal_guard(a):
    if a["status"] == "TERMINATED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "agreement is TERMINATED")


@bp.post("/snack-mfg/co-man-agreements/<aid>/activate")
def activate_agreement(aid):
    require(["PlantManager"])
    a = get_agreement(STORE, aid)
    _agreement_terminal_guard(a)
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "agreement is not DRAFT")
    coman = STORE.comans.get(a["co_manufacturer_id"])
    if coman is None or coman["active"] is not True:
        raise ApiError("ERR_INVALID_STATE", 409, "co-manufacturer is not active")
    a["status"] = "ACTIVE"
    touch(STORE, a)
    return ok(STORE, dump_agreement(a))


@bp.post("/snack-mfg/co-man-agreements/<aid>/suspend")
def suspend_agreement(aid):
    require(["PlantManager"])
    a = get_agreement(STORE, aid)
    _agreement_terminal_guard(a)
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "agreement is not ACTIVE")
    a["status"] = "SUSPENDED"
    touch(STORE, a)
    return ok(STORE, dump_agreement(a))


@bp.post("/snack-mfg/co-man-agreements/<aid>/resume")
def resume_agreement(aid):
    require(["PlantManager"])
    a = get_agreement(STORE, aid)
    _agreement_terminal_guard(a)
    if a["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "agreement is not SUSPENDED")
    a["status"] = "ACTIVE"
    touch(STORE, a)
    return ok(STORE, dump_agreement(a))


@bp.post("/snack-mfg/co-man-agreements/<aid>/terminate")
def terminate_agreement(aid):
    require(["PlantManager"])
    a = get_agreement(STORE, aid)
    _agreement_terminal_guard(a)
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "agreement is not ACTIVE or SUSPENDED")
    a["status"] = "TERMINATED"
    for s in STORE.slots.values():
        if s["agreement_id"] == a["id"] and s["status"] in ("BOOKED", "CONFIRMED"):
            s["status"] = "RELEASED"
            touch(STORE, s)
    touch(STORE, a)
    return ok(STORE, dump_agreement(a))


# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------

@bp.post("/snack-mfg/co-man-slots")
def create_slot():
    uid, role = require(COMAN_RW)
    data = body()
    # tier 3: body FK existence in canonical order (product_id before agreement_id)
    agreement_id = data.get("agreement_id")
    product_id = data.get("product_id")
    product = get_product(STORE, product_id) if isinstance(product_id, str) else None
    if product is None:
        if not isinstance(product_id, str) or product_id == "":
            raise ApiError("ERR_VALIDATION", 400, "missing or invalid field: product_id")
        raise ApiError("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
    agreement = get_agreement(STORE, agreement_id) if isinstance(agreement_id, str) else None
    if agreement is None:
        if not isinstance(agreement_id, str) or agreement_id == "":
            raise ApiError("ERR_VALIDATION", 400, "missing or invalid field: agreement_id")
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "agreement not found")
    # tier 4: ownership scope
    _own_agreement_or_forbid(agreement, uid, role)
    # tier 5: shape
    try:
        week_start = parse_date(data.get("week_start_date"))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "week_start_date must be YYYY-MM-DD")
    reserved_lbs = rhu(req_num(data, "reserved_lbs", gt=0), 2)
    # tier 6: agreement must be ACTIVE
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409, "agreement is not ACTIVE")
    # tier 8: week start must be a Monday
    if week_start.weekday() != 0:
        raise ApiError("ERR_WEEK_START_INVALID", 422, "week_start_date must be a Monday")
    # tier 9: weekly aggregate capacity (checked before budget)
    iso_week = week_start.isocalendar()[:2]
    capacity_used = sum(
        s["reserved_lbs"] for s in STORE.slots.values()
        if s["agreement_id"] == agreement["id"] and s["status"] in ("BOOKED", "CONFIRMED")
        and parse_date(s["week_start_date"]).isocalendar()[:2] == iso_week)
    if capacity_used + reserved_lbs > D(agreement["weekly_capacity_lbs"]):
        raise ApiError("ERR_CAPACITY_EXCEEDED", 422, "weekly capacity would be exceeded")
    # tier 10: budget ceiling
    rate = Decimal(agreement["rate_per_lb_cents"])
    budget_used = sum(s["reserved_lbs"] * rate for s in STORE.slots.values()
                      if s["agreement_id"] == agreement["id"]
                      and s["status"] in ("BOOKED", "CONFIRMED"))
    if budget_used + reserved_lbs * rate > Decimal(agreement["budget_cents"]):
        raise ApiError("ERR_BUDGET_EXCEEDED", 422, "budget ceiling would be exceeded")
    s = new_entity(STORE)
    s.update({
        "agreement_id": agreement["id"], "product_id": product["id"],
        "week_start_date": week_start.isoformat(), "reserved_lbs": reserved_lbs,
        "status": "BOOKED",
    })
    STORE.slots[s["id"]] = s
    return ok(STORE, dump_slot(s), status=201)


def _slot_agreement(slot):
    return STORE.agreements.get(slot["agreement_id"])


@bp.get("/snack-mfg/co-man-slots/<sid>")
def get_slot_ep(sid):
    uid, role = require(COMAN_RW)
    s = get_slot(STORE, sid)
    agreement = _slot_agreement(s)
    if agreement is not None:
        _own_agreement_or_forbid(agreement, uid, role)
    return ok(STORE, dump_slot(s))


@bp.get("/snack-mfg/co-man-slots")
def list_slots():
    uid, role = require(COMAN_RW)
    items = list(STORE.slots.values())
    if role == "CoManufacturer":
        own = {aid for aid, a in STORE.agreements.items() if a["co_manufacturer_id"] == uid}
        items = [s for s in items if s["agreement_id"] in own]
    agreement_id = request.args.get("agreement_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    if agreement_id is not None:
        items = [s for s in items if s["agreement_id"] == agreement_id]
    if product_id is not None:
        items = [s for s in items if s["product_id"] == product_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=sort_key)
    page, meta = paginate([dump_slot(s) for s in items])
    return ok(STORE, page, response_type="array", pagination=meta)


def _slot_terminal_guard(s):
    if s["status"] in ("CONSUMED", "RELEASED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "slot is in a terminal state")


@bp.post("/snack-mfg/co-man-slots/<sid>/confirm")
def confirm_slot(sid):
    uid, role = require(["CoManufacturer"])
    s = get_slot(STORE, sid)
    agreement = get_agreement(STORE, s["agreement_id"])
    # tier 4 ownership precedes state checks
    _own_agreement_or_forbid(agreement, uid, role)
    _slot_terminal_guard(s)
    if s["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "slot is not BOOKED")
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409, "agreement is not ACTIVE")
    s["status"] = "CONFIRMED"
    touch(STORE, s)
    return ok(STORE, dump_slot(s))


@bp.post("/snack-mfg/co-man-slots/<sid>/release")
def release_slot(sid):
    uid, role = require(COMAN_RW)
    s = get_slot(STORE, sid)
    agreement = get_agreement(STORE, s["agreement_id"])
    _own_agreement_or_forbid(agreement, uid, role)
    _slot_terminal_guard(s)
    if s["status"] not in ("BOOKED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "slot cannot be released from this state")
    s["status"] = "RELEASED"
    touch(STORE, s)
    return ok(STORE, dump_slot(s))


@bp.post("/snack-mfg/co-man-slots/<sid>/consume")
def consume_slot(sid):
    require(["PlantManager"])
    s = get_slot(STORE, sid)
    _slot_terminal_guard(s)
    if s["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "slot is not CONFIRMED")
    agreement = get_agreement(STORE, s["agreement_id"])
    if agreement["status"] == "TERMINATED":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409, "agreement is TERMINATED")
    s["status"] = "CONSUMED"
    touch(STORE, s)
    return ok(STORE, dump_slot(s))
