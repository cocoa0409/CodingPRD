"""Material transfers through the pass-through airlock (PRD 3.5)."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, new_record, mutate, pub, iso_ms, now, parse_iso, trunc_second
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_ROOM_NOT_ACTIVE,
    ERR_ROOM_NOT_IN_CONTROL,
    ERR_ROOM_NOT_CERTIFIED,
    ERR_TRANSFER_NOT_STAGED,
    ERR_WIPE_DOWN_MISSING,
    ERR_DWELL_TIME_NOT_MET,
)
from middleware import require_role, body, QA, MH
from response import ok, paginate
from services.core import req_string, req_int, req_bool, touch_room

bp = Blueprint("transfers", __name__)
READERS = [QA, MH]


def load_transfer(transfer_id):
    transfer = store.transfers.get(transfer_id)
    if transfer is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "material transfer %s not found" % transfer_id)
    return transfer


@bp.post("/cleanroom/material-transfers")
def create_transfer():
    require_role([MH])
    payload = body()
    cleanroom_id = payload.get("cleanroom_id")
    if not isinstance(cleanroom_id, str) \
            or store.rooms.get(cleanroom_id) is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "cleanroom %s not found" % cleanroom_id)
    room = touch_room(store.rooms[cleanroom_id])
    if room["status"] != "ACTIVE":
        raise ApiError(ERR_ROOM_NOT_ACTIVE, 409, "room is not ACTIVE")
    transfer = new_record({
        "cleanroom_id": cleanroom_id,
        "material_lot": req_string(payload, "material_lot"),
        "item_description": req_string(payload, "item_description"),
        "staged_at": iso_ms(now()),
        "dwell_minutes": req_int(payload, "dwell_minutes", minimum=0),
        "wiped_down": req_bool(payload, "wiped_down"),
        "status": "STAGED",
    })
    store.transfers[transfer["id"]] = transfer
    return ok(pub(transfer), 201)


@bp.get("/cleanroom/material-transfers")
def list_transfers():
    require_role(READERS)
    records = list(store.transfers.values())
    cleanroom_id = request.args.get("cleanroom_id")
    status = request.args.get("status")
    if cleanroom_id is not None:
        records = [t for t in records if t["cleanroom_id"] == cleanroom_id]
    if status is not None:
        records = [t for t in records if t["status"] == status]
    return paginate(records, request.args)


@bp.get("/cleanroom/material-transfers/<transferId>")
def get_transfer(transferId):
    require_role(READERS)
    return ok(pub(load_transfer(transferId)))


@bp.post("/cleanroom/material-transfers/<transferId>/introduce")
def introduce_transfer(transferId):
    require_role([MH])
    transfer = load_transfer(transferId)
    if transfer["status"] != "STAGED":
        raise ApiError(ERR_TRANSFER_NOT_STAGED, 409, "transfer is not STAGED")
    room = touch_room(store.rooms[transfer["cleanroom_id"]])
    if room["status"] != "ACTIVE":
        raise ApiError(ERR_ROOM_NOT_ACTIVE, 409, "room is not ACTIVE")
    if room["environment_posture"] != "IN_CONTROL":
        raise ApiError(ERR_ROOM_NOT_IN_CONTROL, 409,
                       "room environment_posture is not IN_CONTROL")
    if room["certification_status"] != "CERTIFIED":
        raise ApiError(ERR_ROOM_NOT_CERTIFIED, 409,
                       "room certification_status is not CERTIFIED")
    if not transfer["wiped_down"]:
        raise ApiError(ERR_WIPE_DOWN_MISSING, 409,
                       "wipe-down protocol step was not performed")
    staged_at = parse_iso(transfer["staged_at"])
    dwell_end = staged_at + timedelta(minutes=transfer["dwell_minutes"])
    if trunc_second(now()) < trunc_second(dwell_end):
        raise ApiError(ERR_DWELL_TIME_NOT_MET, 409,
                       "airlock dwell time has not elapsed")
    transfer["status"] = "INTRODUCED"
    mutate(transfer)
    return ok(pub(transfer))


@bp.post("/cleanroom/material-transfers/<transferId>/reject")
def reject_transfer(transferId):
    require_role([MH])
    transfer = load_transfer(transferId)
    if transfer["status"] != "STAGED":
        raise ApiError(ERR_TRANSFER_NOT_STAGED, 409, "transfer is not STAGED")
    transfer["status"] = "REJECTED"
    mutate(transfer)
    return ok(pub(transfer))
