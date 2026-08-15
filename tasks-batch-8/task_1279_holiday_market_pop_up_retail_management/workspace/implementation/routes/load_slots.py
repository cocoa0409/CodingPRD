"""LoadSlot endpoints (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint

import clock
import db
from errors import ApiError, invalid_state
from middleware import auth, require_roles, require_vendor_owner
from response import success
from services.core import (
    DIRECTIONS,
    arg,
    as_dt,
    as_enum,
    as_str,
    base_record,
    body,
    get_child,
    get_market,
    list_response,
    required,
    serialize,
    touch,
)

bp = Blueprint("load_slots", __name__)

MO = ("MarketOperator",)
VENDOR = ("VendorRole",)
GET_ROLES = ("MarketOperator", "VendorRole")
ACTIVE_STATUSES = ("RESERVED", "CHECKED_IN")


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _owner_vendor_id(load_slot):
    assignment = db.STORES["assignments"].get(load_slot["assignment_id"])
    if assignment is None:
        return None
    app = db.STORES["applications"].get(assignment["application_id"])
    return app["vendor_id"] if app else None


def _resolve(marketId, loadSlotId):
    get_market(marketId)
    return get_child("load_slots", loadSlotId, marketId)


@bp.post("/markets/<marketId>/load_slots")
def create_load_slot(marketId):
    user = auth()
    require_roles(user, MO)
    get_market(marketId)
    data = body()
    assignment_id = as_str(required(data, "assignment_id"), "assignment_id")
    assignment = get_child("assignments", assignment_id, marketId)
    direction = as_enum(required(data, "direction"), "direction", DIRECTIONS)
    starts_at = as_dt(required(data, "starts_at"), "starts_at")
    ends_at = as_dt(required(data, "ends_at"), "ends_at")
    if not starts_at < ends_at:
        raise ApiError("ERR_SLOT_CONFLICT", "starts_at must be strictly before ends_at", 409)
    booth_id = assignment["booth_id"]
    for slot in db.STORES["load_slots"].values():
        if slot["market_id"] != marketId or slot["status"] not in ACTIVE_STATUSES:
            continue
        other = db.STORES["assignments"].get(slot["assignment_id"])
        if other is None or other["booth_id"] != booth_id:
            continue
        if _overlaps(starts_at, ends_at, slot["starts_at"], slot["ends_at"]):
            raise ApiError(
                "ERR_SLOT_CONFLICT",
                "interval overlaps an existing load slot on the same market and booth",
                409,
            )
    rec = base_record()
    rec.update(
        {
            "market_id": marketId,
            "assignment_id": assignment_id,
            "direction": direction,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "status": "RESERVED",
        }
    )
    db.STORES["load_slots"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/markets/<marketId>/load_slots/<loadSlotId>")
def get_load_slot(marketId, loadSlotId):
    user = auth()
    require_roles(user, GET_ROLES)
    return success(serialize(_resolve(marketId, loadSlotId)))


@bp.get("/markets/<marketId>/load_slots")
def list_load_slots(marketId):
    user = auth()
    require_roles(user, GET_ROLES)
    get_market(marketId)
    status = arg("status")
    assignment_id = arg("assignment_id")
    direction = arg("direction")
    records = []
    for s in db.STORES["load_slots"].values():
        if s["market_id"] != marketId:
            continue
        if status is not None and s["status"] != status:
            continue
        if assignment_id is not None and s["assignment_id"] != assignment_id:
            continue
        if direction is not None and s["direction"] != direction:
            continue
        records.append(s)
    return list_response(records)


@bp.post("/markets/<marketId>/load_slots/<loadSlotId>/check_in")
def check_in_load_slot(marketId, loadSlotId):
    user = auth()
    require_roles(user, VENDOR)
    slot = _resolve(marketId, loadSlotId)
    require_vendor_owner(user, _owner_vendor_id(slot))
    if slot["status"] != "RESERVED":
        raise invalid_state("only a RESERVED load slot can be checked in")
    now = clock.now()
    if not (slot["starts_at"] - timedelta(minutes=30) <= now <= slot["ends_at"]):
        raise invalid_state(
            "check-in is only accepted between 30 minutes before starts_at and ends_at"
        )
    slot["status"] = "CHECKED_IN"
    touch(slot)
    return success(serialize(slot))


@bp.post("/markets/<marketId>/load_slots/<loadSlotId>/complete")
def complete_load_slot(marketId, loadSlotId):
    user = auth()
    require_roles(user, VENDOR)
    slot = _resolve(marketId, loadSlotId)
    require_vendor_owner(user, _owner_vendor_id(slot))
    if slot["status"] != "CHECKED_IN":
        raise invalid_state("only a CHECKED_IN load slot can be completed")
    if clock.now() > slot["ends_at"] + timedelta(minutes=60):
        raise invalid_state("completion is only accepted up to 60 minutes after ends_at")
    slot["status"] = "COMPLETED"
    touch(slot)
    return success(serialize(slot))
