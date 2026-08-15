"""DutyRosterSlot endpoints: assign, confirm, swap handshake."""

import uuid

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_NOT_SLOT_OWNER,
    ERR_RESOURCE_NOT_FOUND,
    ERR_SLOT_NOT_ASSIGNED,
    ERR_SWAP_INVALID,
    ERR_SWAP_SAME_MEMBER,
    ERR_SWAP_TARGET_NOT_ASSIGNED,
)
from middleware import auth, require_role
from response import success
from services import ser_duty_slot, touch
from util import get_body, need_str, paginate, parse_dt, sort_items

bp = Blueprint("duty", __name__)


def _get_slot_or_404(sid):
    slot = db.STORE["duty_slots"].get(sid)
    if slot is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "DutyRosterSlot not found")
    return slot


def _not_owner():
    raise ApiError(
        ERR_NOT_SLOT_OWNER, 403,
        "The acting member does not own the required duty slot",
    )


@bp.post("/soaring/duty-roster")
def create_slot():
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    body = get_body()
    # duty_date is the calendar date, recorded at 00:00Z.
    duty_date = parse_dt(
        body.get("duty_date") if body.get("duty_date") is not None else None,
        field="duty_date",
    ).replace(hour=0, minute=0, second=0, microsecond=0)
    member_id = need_str(body, "member_id")
    if member_id not in db.STORE["members"]:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Member not found")
    record = {
        "id": str(uuid.uuid4()),
        "duty_date": duty_date,
        "member_id": member_id,
        "status": "ASSIGNED",
        "swap_with_slot_id": None,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.STORE["duty_slots"][record["id"]] = record
    return success(ser_duty_slot(record), "object", 201)


@bp.get("/soaring/duty-roster")
def list_slots():
    auth()
    items = list(db.STORE["duty_slots"].values())
    for param in ("member_id", "status", "swap_with_slot_id"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s.get(param) == value]
    page, meta = paginate(sort_items(items))
    return success([ser_duty_slot(s) for s in page], "array", 200, meta)


@bp.get("/soaring/duty-roster/<sid>")
def get_slot(sid):
    auth()
    return success(ser_duty_slot(_get_slot_or_404(sid)), "object", 200)


@bp.post("/soaring/duty-roster/<sid>/confirm")
def confirm_slot(sid):
    user_id, role = auth()
    require_role(role, ["Member"])
    slot = _get_slot_or_404(sid)
    if slot["member_id"] != user_id:
        _not_owner()
    if slot["status"] != "ASSIGNED":
        raise ApiError(
            ERR_SLOT_NOT_ASSIGNED, 409,
            "Confirm requires duty slot status ASSIGNED",
        )
    slot["status"] = "CONFIRMED"
    touch(slot)
    return success(ser_duty_slot(slot), "object", 200)


@bp.post("/soaring/duty-roster/<sid>/propose-swap")
def propose_swap(sid):
    user_id, role = auth()
    require_role(role, ["Member"])
    origin = _get_slot_or_404(sid)
    body = get_body()
    target_id = need_str(body, "swap_with_slot_id")
    target = db.STORE["duty_slots"].get(target_id)
    if target is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Swap target slot not found")
    if origin["member_id"] != user_id:
        _not_owner()
    if origin["status"] != "ASSIGNED":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only an ASSIGNED slot can propose a swap",
        )
    if target["status"] != "ASSIGNED":
        raise ApiError(
            ERR_SWAP_TARGET_NOT_ASSIGNED, 409,
            "The swap target slot is not ASSIGNED",
        )
    if target["member_id"] == origin["member_id"]:
        raise ApiError(
            ERR_SWAP_SAME_MEMBER, 422,
            "Cannot swap with a slot owned by the same member",
        )
    # The target must not already stand as the recorded partner of a
    # different slot's pending swap.
    for other in db.STORE["duty_slots"].values():
        if (
            other["id"] != origin["id"]
            and other["status"] == "SWAP_PENDING"
            and other["swap_with_slot_id"] == target["id"]
        ):
            raise ApiError(
                ERR_SWAP_INVALID, 409,
                "Swap target is already paired with a different pending swap",
            )
    origin["status"] = "SWAP_PENDING"
    origin["swap_with_slot_id"] = target["id"]
    touch(origin)
    return success(ser_duty_slot(origin), "object", 200)


@bp.post("/soaring/duty-roster/<sid>/accept-swap")
def accept_swap(sid):
    user_id, role = auth()
    require_role(role, ["Member"])
    origin = _get_slot_or_404(sid)
    target = (
        db.STORE["duty_slots"].get(origin["swap_with_slot_id"])
        if origin.get("swap_with_slot_id")
        else None
    )
    # Accept belongs to the target slot's owner alone.
    if target is None or target["member_id"] != user_id:
        _not_owner()
    if origin["status"] != "SWAP_PENDING":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a SWAP_PENDING slot can be accepted",
        )
    if target["status"] != "ASSIGNED":
        raise ApiError(
            ERR_SWAP_INVALID, 409,
            "The swap pair is no longer intact",
        )
    origin["member_id"], target["member_id"] = target["member_id"], origin["member_id"]
    origin["status"] = "ASSIGNED"
    target["status"] = "ASSIGNED"
    origin["swap_with_slot_id"] = None
    target["swap_with_slot_id"] = None
    touch(origin)
    touch(target)
    return success(ser_duty_slot(origin), "object", 200)


@bp.post("/soaring/duty-roster/<sid>/decline-swap")
def decline_swap(sid):
    user_id, role = auth()
    require_role(role, ["Member"])
    origin = _get_slot_or_404(sid)
    target = (
        db.STORE["duty_slots"].get(origin["swap_with_slot_id"])
        if origin.get("swap_with_slot_id")
        else None
    )
    # Either slot's owner may decline.
    owners = {origin["member_id"]}
    if target is not None:
        owners.add(target["member_id"])
    if user_id not in owners:
        _not_owner()
    if origin["status"] != "SWAP_PENDING":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a SWAP_PENDING slot can be declined",
        )
    origin["status"] = "ASSIGNED"
    origin["swap_with_slot_id"] = None
    touch(origin)
    return success(ser_duty_slot(origin), "object", 200)
