"""Shift assignment endpoints."""
from flask import Blueprint

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok
from services import (
    check_shift_overlap,
    lookup,
    ser_shift,
    stamp,
    touch,
)
from util import body, req_enum, req_str

bp = Blueprint("shifts", __name__)


@bp.post("/shift-assignments")
def create_shift():
    auth(["DocentCoordinator"])
    data = body()
    # Tier 3 (existence): body FKs.
    raw_docent = data.get("docent_id")
    raw_slot = data.get("slot_id")
    docent = lookup("docents", raw_docent) if raw_docent is not None else None
    slot = lookup("slots", raw_slot) if raw_slot is not None else None
    # Tier 4 (request shape).
    if docent is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: docent_id")
    if slot is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: slot_id")
    shift_role = req_enum(data, "shift_role", ("LEAD", "SHADOW"))
    # Tier 9 (cross-entity): qualification against the slot's route.
    if shift_role == "LEAD":
        qualified = docent["status"] == "CERTIFIED" and (
            slot["route_id"] in docent["certified_route_ids"]
        )
    else:
        qualified = docent["status"] in ("TRAINEE", "CERTIFIED")
    if not qualified:
        raise ApiError(
            "ERR_DOCENT_NOT_QUALIFIED",
            422,
            "Docent is not qualified for this shift role on this route",
        )
    # Tier 10 (temporal): 30-minute-buffer double-booking guard.
    check_shift_overlap(docent["id"], slot["_start_dt"], slot["_end_dt"])
    # Tier 11 (fiscal): at most one non-terminal LEAD per slot.
    if shift_role == "LEAD":
        for other in DB["shifts"].values():
            if (
                other["slot_id"] == slot["id"]
                and other["shift_role"] == "LEAD"
                and other["status"] in ("ASSIGNED", "CONFIRMED")
            ):
                raise ApiError(
                    "ERR_LEAD_ALREADY_ASSIGNED",
                    409,
                    "Slot already has a non-terminal LEAD shift",
                )
    rec = {
        "id": new_id(),
        "docent_id": docent["id"],
        "slot_id": slot["id"],
        "shift_role": shift_role,
        "status": "ASSIGNED",
    }
    stamp(rec)
    DB["shifts"][rec["id"]] = rec
    return ok(ser_shift(rec), 201)


@bp.post("/shift-assignments/<sid>/confirm")
def confirm_shift(sid):
    user_id, _ = auth(["Docent"])
    shift = lookup("shifts", sid)
    if shift["docent_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Docents may confirm only their own shifts"
        )
    if shift["status"] != "ASSIGNED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an ASSIGNED shift can be confirmed"
        )
    shift["status"] = "CONFIRMED"
    touch(shift)
    return ok(ser_shift(shift))


@bp.post("/shift-assignments/<sid>/decline")
def decline_shift(sid):
    user_id, _ = auth(["Docent"])
    shift = lookup("shifts", sid)
    if shift["docent_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Docents may decline only their own shifts"
        )
    if shift["status"] != "ASSIGNED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an ASSIGNED shift can be declined"
        )
    shift["status"] = "DECLINED"
    touch(shift)
    return ok(ser_shift(shift))


@bp.post("/shift-assignments/<sid>/resolve")
def resolve_shift(sid):
    auth(["DocentCoordinator"])
    shift = lookup("shifts", sid)
    data = body()
    outcome = req_enum(data, "outcome", ("COMPLETED", "NO_SHOW"))
    if shift["status"] != "CONFIRMED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a CONFIRMED shift can be resolved"
        )
    slot = lookup("slots", shift["slot_id"])
    if slot["status"] != "COMPLETED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Shifts can be resolved only after the slot is COMPLETED",
        )
    shift["status"] = outcome
    touch(shift)
    return ok(ser_shift(shift))
