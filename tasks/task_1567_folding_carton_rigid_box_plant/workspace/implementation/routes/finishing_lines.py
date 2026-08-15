"""FinishingLine registry endpoints (PRD §3.6)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    get_body,
    get_or_404,
    list_response,
    req_enum,
    req_int,
    req_list,
    req_str,
    ser_plain,
)
from util import touch

bp = Blueprint("finishing_lines", __name__)

OPERATIONS = ("COAT", "FOIL", "EMBOSS")
LINE_STATUSES = ("ACTIVE", "DOWN")


@bp.post("/plant/finishing-lines")
def create_finishing_line():
    authenticate(("PlantAdmin",))
    data = get_body()
    line_code = req_str(data, "line_code")
    supported_ops = req_list(data, "supported_ops")
    for op in supported_ops:
        if not isinstance(op, str) or op not in OPERATIONS:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "supported_ops entries must be members of [COAT, FOIL, EMBOSS]")
    setup_buffer_minutes = req_int(data, "setup_buffer_minutes", 0)
    rec = db.new_record()
    rec.update({
        "line_code": line_code,
        "supported_ops": list(supported_ops),
        "setup_buffer_minutes": setup_buffer_minutes,
        "status": "ACTIVE",
    })
    db.finishing_lines[rec["id"]] = rec
    return ok_object(ser_plain(rec), 201)


@bp.get("/plant/finishing-lines")
def list_finishing_lines():
    authenticate(ALL_ROLES)
    return list_response(
        db.finishing_lines.values(), ser_plain, [("status", "status", "str")])


@bp.get("/plant/finishing-lines/<lineId>")
def get_finishing_line(lineId):
    authenticate(ALL_ROLES)
    return ok_object(ser_plain(get_or_404(db.finishing_lines, lineId)))


@bp.post("/plant/finishing-lines/<lineId>/set-status")
def set_finishing_line_status(lineId):
    authenticate(("PlantAdmin",))
    rec = get_or_404(db.finishing_lines, lineId)
    data = get_body()
    to_status = req_enum(data, "to_status", LINE_STATUSES)
    if to_status == rec["status"]:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Finishing line is already %s" % to_status)
    rec["status"] = to_status
    touch(rec)
    return ok_object(ser_plain(rec))
