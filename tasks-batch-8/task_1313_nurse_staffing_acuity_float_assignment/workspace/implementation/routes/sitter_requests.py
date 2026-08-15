"""SitterRequest endpoints: 1:1 observation coverage diverted from confirmed
staff."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_UNIT_NOT_FOUND,
    ERR_NURSE_NOT_FOUND,
    ERR_SITTER_REQUEST_NOT_FOUND,
    ERR_SITTER_INVALID_STATE,
    ERR_NO_COVERING_ASSIGNMENT,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.core import (
    find_covering_assignment,
    refresh_shift_and_touch,
    shift_of,
    pub,
)
from util import (
    get_json_body,
    req_str,
    req_iso_datetime,
    parse_pagination,
    paginate,
    apply_filters,
)

bp = Blueprint("sitter_requests", __name__)


@bp.post("/sitter-requests")
@require_roles("ChargeNurse")
def create_sitter_request(_user_id: str, _role: str):
    body = get_json_body()

    # Body FK: presence, then existence.
    if "unit_id" not in body or body["unit_id"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: unit_id")
    unit_id = body["unit_id"]
    if not isinstance(unit_id, str) or unit_id == "":
        raise_err(ERR_INVALID_REQUEST, "unit_id must be a string")
    unit = db.units.get(unit_id)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "Unit not found")

    patient_ref = req_str(body, "patient_ref")
    start_raw = body.get("start_at")
    end_raw = body.get("end_at")
    start_dt = req_iso_datetime(body, "start_at")
    end_dt = req_iso_datetime(body, "end_at")
    if not (end_dt > start_dt):
        raise_err(ERR_INVALID_REQUEST, "end_at must be strictly after start_at")

    sitter = {
        "unit_id": unit_id,
        "patient_ref": patient_ref,
        "start_at": start_raw,
        "end_at": end_raw,
        "status": "PENDING",
        "assigned_nurse_id": None,
        "covering_assignment_id": None,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    db.stamp_new(sitter)
    db.sitter_requests[sitter["id"]] = sitter
    return success_object(pub(sitter), 201)


@bp.get("/sitter-requests")
@require_roles(*ALL_ROLES)
def list_sitter_requests(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sorted(db.sitter_requests.values(), key=lambda s: s["created_at"])
    items = apply_filters(items, {
        "unit_id": request.args.get("unit_id"),
        "assigned_nurse_id": request.args.get("assigned_nurse_id"),
        "covering_assignment_id": request.args.get("covering_assignment_id"),
        "status": request.args.get("status"),
    })
    page, total = paginate(items, limit, offset)
    return success_list([pub(s) for s in page], limit, offset, total)


@bp.get("/sitter-requests/<sitterRequestId>")
@require_roles(*ALL_ROLES)
def get_sitter_request(sitterRequestId: str, _user_id: str, _role: str):
    sitter = db.sitter_requests.get(sitterRequestId)
    if sitter is None:
        raise_err(ERR_SITTER_REQUEST_NOT_FOUND, "Sitter request not found")
    return success_object(pub(sitter))


@bp.post("/sitter-requests/<sitterRequestId>/fill")
@require_roles("ChargeNurse")
def fill_sitter_request(sitterRequestId: str, _user_id: str, _role: str):
    sitter = db.sitter_requests.get(sitterRequestId)
    if sitter is None:
        raise_err(ERR_SITTER_REQUEST_NOT_FOUND, "Sitter request not found")

    body = get_json_body()
    if "nurse_id" not in body or body["nurse_id"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: nurse_id")
    nurse_id = body["nurse_id"]
    if not isinstance(nurse_id, str) or nurse_id == "":
        raise_err(ERR_INVALID_REQUEST, "nurse_id must be a string")
    nurse = db.nurses.get(nurse_id)
    if nurse is None:
        raise_err(ERR_NURSE_NOT_FOUND, "Nurse not found")

    if sitter["status"] != "PENDING":
        raise_err(ERR_SITTER_INVALID_STATE, "fill requires a PENDING sitter request")

    covering = find_covering_assignment(
        nurse_id, sitter["unit_id"], sitter["_start_dt"], sitter["_end_dt"]
    )
    if covering is None:
        raise_err(ERR_NO_COVERING_ASSIGNMENT,
                  "Nurse has no available CONFIRMED assignment on the unit containing the window")

    sitter["status"] = "FILLED"
    sitter["assigned_nurse_id"] = nurse_id
    sitter["covering_assignment_id"] = covering["id"]
    db.touch(sitter)
    refresh_shift_and_touch(shift_of(covering))
    return success_object(pub(sitter), 200)


@bp.post("/sitter-requests/<sitterRequestId>/release")
@require_roles("ChargeNurse")
def release_sitter_request(sitterRequestId: str, _user_id: str, _role: str):
    sitter = db.sitter_requests.get(sitterRequestId)
    if sitter is None:
        raise_err(ERR_SITTER_REQUEST_NOT_FOUND, "Sitter request not found")
    if sitter["status"] != "FILLED":
        raise_err(ERR_SITTER_INVALID_STATE, "release requires a FILLED sitter request")

    covering = db.assignments.get(sitter.get("covering_assignment_id") or "")
    sitter["status"] = "RELEASED"
    db.touch(sitter)
    if covering is not None:
        refresh_shift_and_touch(shift_of(covering))
    return success_object(pub(sitter), 200)
