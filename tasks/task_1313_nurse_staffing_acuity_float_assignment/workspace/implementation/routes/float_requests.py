"""FloatRequest endpoints: synchronous float pool deployment."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_SHIFT_NOT_FOUND,
    ERR_FLOAT_REQUEST_NOT_FOUND,
    ERR_FLOAT_REQUEST_NOT_RELEASABLE,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.core import (
    create_float_request,
    refresh_shift_and_touch,
    pub,
)
from util import get_json_body, parse_pagination, paginate, apply_filters

bp = Blueprint("float_requests", __name__)


@bp.post("/float-requests")
@require_roles("FloatCoordinator")
def create_float_request_endpoint(_user_id: str, _role: str):
    body = get_json_body()
    if "shift_id" not in body or body["shift_id"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: shift_id")
    shift_id = body["shift_id"]
    if not isinstance(shift_id, str) or shift_id == "":
        raise_err(ERR_INVALID_REQUEST, "shift_id must be a string")
    shift = db.shifts.get(shift_id)
    if shift is None:
        raise_err(ERR_SHIFT_NOT_FOUND, "Shift not found")

    fr = create_float_request(shift, origin="MANUAL")
    return success_object(pub(fr), 201)


@bp.get("/float-requests")
@require_roles(*ALL_ROLES)
def list_float_requests(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sorted(db.float_requests.values(), key=lambda f: f["created_at"])
    items = apply_filters(items, {
        "shift_id": request.args.get("shift_id"),
        "deployed_nurse_id": request.args.get("deployed_nurse_id"),
        "assignment_id": request.args.get("assignment_id"),
        "status": request.args.get("status"),
    })
    page, total = paginate(items, limit, offset)
    return success_list([pub(f) for f in page], limit, offset, total)


@bp.get("/float-requests/<floatRequestId>")
@require_roles(*ALL_ROLES)
def get_float_request(floatRequestId: str, _user_id: str, _role: str):
    fr = db.float_requests.get(floatRequestId)
    if fr is None:
        raise_err(ERR_FLOAT_REQUEST_NOT_FOUND, "Float request not found")
    return success_object(pub(fr))


@bp.post("/float-requests/<floatRequestId>/release")
@require_roles("FloatCoordinator")
def release_float_request(floatRequestId: str, _user_id: str, _role: str):
    fr = db.float_requests.get(floatRequestId)
    if fr is None:
        raise_err(ERR_FLOAT_REQUEST_NOT_FOUND, "Float request not found")
    if fr["status"] != "DEPLOYED":
        raise_err(ERR_FLOAT_REQUEST_NOT_RELEASABLE,
                  "release requires a DEPLOYED float request")
    assignment = db.assignments.get(fr.get("assignment_id") or "")
    if assignment is None or assignment["status"] != "PROPOSED":
        raise_err(ERR_FLOAT_REQUEST_NOT_RELEASABLE,
                  "release requires the linked assignment to still be PROPOSED")

    fr["status"] = "RELEASED"
    db.touch(fr)
    assignment["status"] = "CANCELLED"
    db.touch(assignment)
    refresh_shift_and_touch(db.shifts[assignment["shift_id"]])
    return success_object(pub(fr), 200)
