"""Transfer requests (PRD §3.7)."""

from flask import Blueprint

import db
import services
from db import clock_date, new_id, parse_date, stamp_new, touch
from errors import (
    ERR_INVALID_REQUEST,
    ERR_RECORD_NOT_ACTIVE,
    ERR_RESOURCE_NOT_OWNED,
    ERR_TRANSFER_NOT_CANCELLABLE,
    raise_error,
)
from helpers import (
    body, get_or_404, get_student_or_404, list_response, req_date, req_enum,
    req_str,
)
from middleware import ALL_ROLES, STAFF_ROLES, require_roles
from response import success_object
from serializers import transfer_request_out

bp = Blueprint("transfers", __name__)

DIRECTIONS = ("OUT", "IN")


@bp.route("/sevis/students/<sid>/transfer-requests", methods=["POST"])
def create_transfer_request(sid):
    require_roles(STAFF_ROLES)
    student = get_student_or_404(sid)
    data = body()
    direction = req_enum(data, "direction", DIRECTIONS)
    target_school_code = req_str(data, "target_school_code")
    release_date = req_date(data, "release_date")
    if direction == "OUT":
        record = services.record_of_student(student["id"])
        if record is None or record["status"] != "ACTIVE":
            raise_error(ERR_RECORD_NOT_ACTIVE, "Outbound transfer requires an ACTIVE record")
        if parse_date(release_date) < clock_date():
            raise_error(ERR_INVALID_REQUEST, "release_date must be on or after the current clock date")
    request_entity = {
        "id": new_id(),
        "student_id": student["id"],
        "direction": direction,
        "target_school_code": target_school_code,
        "release_date": release_date,
        "status": "REQUESTED",
    }
    stamp_new(request_entity)
    db.transfer_requests[request_entity["id"]] = request_entity
    return success_object(transfer_request_out(request_entity), 201)


@bp.route("/sevis/students/<sid>/transfer-requests", methods=["GET"])
def list_transfer_requests(sid):
    user_id, role = require_roles(ALL_ROLES)
    if role == "Student" and user_id != sid:
        raise_error(ERR_RESOURCE_NOT_OWNED, "Students may only read their own resources")
    student = get_student_or_404(sid)
    items = [t for t in db.transfer_requests.values() if t["student_id"] == student["id"]]
    return list_response(items, transfer_request_out)


@bp.route("/sevis/transfer-requests/<tid>/cancel", methods=["POST"])
def cancel_transfer_request(tid):
    require_roles(STAFF_ROLES)
    request_entity = get_or_404(db.transfer_requests, tid, "TransferRequest")
    if request_entity["status"] != "REQUESTED":
        raise_error(ERR_TRANSFER_NOT_CANCELLABLE, "Transfer must be REQUESTED to cancel")
    if clock_date() >= parse_date(request_entity["release_date"]):
        raise_error(ERR_TRANSFER_NOT_CANCELLABLE, "Transfer release date has been reached")
    request_entity["status"] = "CANCELLED"
    touch(request_entity)
    return success_object(transfer_request_out(request_entity), 200)
