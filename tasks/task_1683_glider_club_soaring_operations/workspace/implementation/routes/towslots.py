"""TowSlot endpoints."""

import uuid

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_REFERENTIAL_INTEGRITY,
    ERR_RESOURCE_NOT_FOUND,
    ERR_TOW_SLOT_IN_USE,
)
from middleware import auth, forbid, require_role
from response import success
from services import ser_tow_slot, touch
from util import get_body, need_dt, need_int, need_str, paginate, sort_items

bp = Blueprint("towslots", __name__)


def _get_slot_or_404(sid):
    slot = db.STORE["tow_slots"].get(sid)
    if slot is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "TowSlot not found")
    return slot


@bp.post("/soaring/tow-slots")
def create_tow_slot():
    user_id, role = auth()
    require_role(role, ["ClubAdmin", "TowPilot"])
    body = get_body()
    tow_plane_id = need_str(body, "tow_plane_id")
    tow_pilot_id = need_str(body, "tow_pilot_id")
    start_at = need_dt(body, "start_at")
    end_at = need_dt(body, "end_at")
    capacity = need_int(body, "capacity")
    # A TowPilot schedules slots they will fly themselves.
    if role == "TowPilot" and tow_pilot_id != user_id:
        forbid("A TowPilot may only schedule slots they will fly")
    plane = db.STORE["aircraft"].get(tow_plane_id)
    if plane is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Tow plane aircraft not found")
    pilot = db.STORE["members"].get(tow_pilot_id)
    if pilot is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Tow pilot member not found")
    if plane["kind"] != "TOW_PLANE":
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422,
            "tow_plane_id must reference an aircraft of kind TOW_PLANE",
        )
    if not pilot["is_tow_pilot"]:
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422,
            "tow_pilot_id must reference a member with is_tow_pilot true",
        )
    if capacity < 1:
        raise ApiError(ERR_REFERENTIAL_INTEGRITY, 422, "capacity must be >= 1")
    record = {
        "id": str(uuid.uuid4()),
        "tow_plane_id": tow_plane_id,
        "tow_pilot_id": tow_pilot_id,
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
        "confirmed_count": 0,
        "status": "SCHEDULED",
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.STORE["tow_slots"][record["id"]] = record
    return success(ser_tow_slot(record), "object", 201)


@bp.get("/soaring/tow-slots")
def list_tow_slots():
    auth()
    items = list(db.STORE["tow_slots"].values())
    for param in ("tow_plane_id", "tow_pilot_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s.get(param) == value]
    page, meta = paginate(sort_items(items))
    return success([ser_tow_slot(s) for s in page], "array", 200, meta)


@bp.get("/soaring/tow-slots/<sid>")
def get_tow_slot(sid):
    auth()
    return success(ser_tow_slot(_get_slot_or_404(sid)), "object", 200)


@bp.post("/soaring/tow-slots/<sid>/cancel")
def cancel_tow_slot(sid):
    _, role = auth()
    require_role(role, ["TowPilot", "ClubAdmin"])
    slot = _get_slot_or_404(sid)
    if slot["status"] != "SCHEDULED":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Only a SCHEDULED tow slot can be cancelled"
        )
    for flight in db.STORE["flights"].values():
        if flight["tow_slot_id"] == sid and flight["status"] == "IN_FLIGHT":
            raise ApiError(
                ERR_TOW_SLOT_IN_USE, 409,
                "An IN_FLIGHT flight is linked to this slot",
            )
    slot["status"] = "CANCELLED"
    touch(slot)
    return success(ser_tow_slot(slot), "object", 200)
