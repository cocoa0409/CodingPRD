"""Press registry endpoints (PRD §3.5)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_STATE_TRANSITION
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    get_body,
    get_or_404,
    list_response,
    req_enum,
    req_int,
    req_str,
    ser_plain,
)
from util import touch

bp = Blueprint("presses", __name__)

PRESS_TYPES = ("DIGITAL", "OFFSET")
PRESS_STATUSES = ("ACTIVE", "DOWN")


@bp.post("/plant/presses")
def create_press():
    authenticate(("PlantAdmin",))
    data = get_body()
    press_code = req_str(data, "press_code")
    press_type = req_enum(data, "press_type", PRESS_TYPES)
    max_sheet_w_cin = req_int(data, "max_sheet_w_cin", 1)
    max_sheet_h_cin = req_int(data, "max_sheet_h_cin", 1)
    max_sheets_per_booking = req_int(data, "max_sheets_per_booking", 1)
    rec = db.new_record()
    rec.update({
        "press_code": press_code,
        "press_type": press_type,
        "max_sheet_w_cin": max_sheet_w_cin,
        "max_sheet_h_cin": max_sheet_h_cin,
        "max_sheets_per_booking": max_sheets_per_booking,
        "status": "ACTIVE",
    })
    db.presses[rec["id"]] = rec
    return ok_object(ser_plain(rec), 201)


@bp.get("/plant/presses")
def list_presses():
    authenticate(ALL_ROLES)
    return list_response(
        db.presses.values(),
        ser_plain,
        [("press_type", "press_type", "str"), ("status", "status", "str")],
    )


@bp.get("/plant/presses/<pressId>")
def get_press(pressId):
    authenticate(ALL_ROLES)
    return ok_object(ser_plain(get_or_404(db.presses, pressId)))


@bp.post("/plant/presses/<pressId>/set-status")
def set_press_status(pressId):
    authenticate(("PlantAdmin",))
    rec = get_or_404(db.presses, pressId)
    data = get_body()
    to_status = req_enum(data, "to_status", PRESS_STATUSES)
    if to_status == rec["status"]:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Press is already %s" % to_status)
    rec["status"] = to_status
    touch(rec)
    return ok_object(ser_plain(rec))
