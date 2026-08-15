"""Carrier endpoints (PRD 3.1): register, list, get, PATCH under OCC, audit-readiness."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_FLEET_SIZE,
    ERR_DUPLICATE_DOT_NUMBER, ERR_STALE_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import stamp_new, touch, sweep_quoted_premiums, audit_readiness
from validate import (
    get_body, req_str, req_int, opt_str, opt_int, opt_bool, opt_datetime,
    require_path_resource,
)
from util import new_id

bp = Blueprint("carriers", __name__)

ROLE = ["SafetyAdmin"]


@bp.post("/safety/carriers")
def create_carrier():
    authorized(ROLE)
    body = get_body()
    # Stage 3: request shape
    dot_number = req_str(body, "dot_number")
    legal_name = req_str(body, "legal_name")
    fleet_size_raw = body.get("fleet_size")
    if fleet_size_raw is None or isinstance(fleet_size_raw, bool) or not isinstance(fleet_size_raw, int):
        raise_error(ERR_INVALID_REQUEST, "missing or invalid integer field: fleet_size")
    if fleet_size_raw < 1:
        raise_error(ERR_INVALID_FLEET_SIZE, "fleet_size must be >= 1")
    is_new_entrant = opt_bool(body, "is_new_entrant", default=False)
    due_raw = body.get("safety_audit_due_date")
    if is_new_entrant:
        if due_raw is None:
            raise_error(ERR_INVALID_REQUEST,
                        "safety_audit_due_date is required when is_new_entrant is true")
        safety_audit_due_date = opt_datetime(body, "safety_audit_due_date")
    else:
        if due_raw is not None:
            raise_error(ERR_INVALID_REQUEST,
                        "safety_audit_due_date is only allowed when is_new_entrant is true")
        safety_audit_due_date = None
    # Stage 9: uniqueness
    for c in db["carriers"].values():
        if c["dot_number"] == dot_number:
            raise_error(ERR_DUPLICATE_DOT_NUMBER, "dot_number already registered")
    carrier = stamp_new({
        "id": new_id(),
        "dot_number": dot_number,
        "legal_name": legal_name,
        "fleet_size": fleet_size_raw,
        "is_new_entrant": is_new_entrant,
        "safety_audit_due_date": safety_audit_due_date,
        "safety_rating": "NONE",
        "new_entrant_status": "PENDING_AUDIT" if is_new_entrant else "NOT_NEW_ENTRANT",
        "rating_cooling_off_until": None,
        "posture": "NORMAL",
        "last_cycle_date": None,
    })
    db["carriers"][carrier["id"]] = carrier
    return success_object(public(carrier), 201)


@bp.get("/safety/carriers")
def list_carriers():
    return list_response("carriers", filters={
        "safety_rating": request.args.get("safety_rating"),
        "posture": request.args.get("posture"),
    })


@bp.get("/safety/carriers/<rid>")
def get_carrier(rid):
    return get_one("carriers", rid)


@bp.patch("/safety/carriers/<rid>")
def patch_carrier(rid):
    authorized(ROLE)
    body = get_body()
    # Stage 3: shape
    legal_name = opt_str(body, "legal_name")
    fleet_size = body.get("fleet_size")
    if fleet_size is not None:
        if isinstance(fleet_size, bool) or not isinstance(fleet_size, int):
            raise_error(ERR_INVALID_REQUEST, "invalid integer field: fleet_size")
        if fleet_size < 1:
            raise_error(ERR_INVALID_FLEET_SIZE, "fleet_size must be >= 1")
    expected = req_int(body, "expected_carrier_version")
    # Stage 4: existence
    carrier = require_path_resource("carriers", rid)
    # Stage 6: optimistic concurrency
    if expected != carrier["version"]:
        raise_error(ERR_STALE_VERSION, "expected_carrier_version is stale")
    if legal_name is not None:
        carrier["legal_name"] = legal_name
    if fleet_size is not None:
        carrier["fleet_size"] = fleet_size
    touch(carrier)
    sweep_quoted_premiums(carrier["id"])
    return success_object(public(carrier))


@bp.get("/safety/carriers/<rid>/audit-readiness")
def get_audit_readiness(rid):
    from middleware import get_caller, check_role_allowed, READ_ROLES
    caller = get_caller()
    check_role_allowed(caller, READ_ROLES)
    carrier = require_path_resource("carriers", rid)
    return success_object(audit_readiness(carrier))
