"""HealthPermit endpoints (PRD §3.2)."""

from flask import request, Blueprint

import errors
import serializers
import services
from db import db
from errors import err
from helpers import (get_body, require_str, require_fk, require_state_code,
                     require_datetime, get_pagination, paginate)
from lookups import get_permit, get_truck
from middleware import require_user_context, require_role
from response import ok_object, ok_array

bp = Blueprint("permits", __name__)

WRITE_ROLES = {"HealthInspector", "PlatformAdmin"}
READ_ROLES = {"HealthInspector", "PlatformAdmin", "Dispatcher", "OperatorTruck"}


@bp.post("/health-permits")
def issue_permit():
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    body = get_body()
    # FK existence (priority 4) before other well-formedness (priority 5).
    truck_id = require_fk(body, "truck_id")
    truck = get_truck(truck_id)
    permit_number = require_str(body, "permit_number")
    state_code = require_state_code(body, "state_code")
    issued_at = require_datetime(body, "issued_at")
    expires_at = require_datetime(body, "expires_at")
    # Well-formedness (priority 5): expires_at strictly after issued_at.
    if not (expires_at > issued_at):
        raise err(errors.ERR_INVALID_REQUEST, "expires_at must be after issued_at")
    # At-most-one-active-permit uniqueness (priority 13).
    for p in db.permits.values():
        if p["truck_id"] == truck_id and p["status"] == "ACTIVE":
            raise err(errors.ERR_DUPLICATE_ACTIVE_PERMIT,
                      "Truck already has an ACTIVE permit")
    rec = db.new_record({
        "truck_id": truck_id,
        "permit_number": permit_number,
        "state_code": state_code,
        "status": "ACTIVE",
        "issued_at": body["issued_at"],
        "expires_at": body["expires_at"],
    })
    db.permits[rec["id"]] = rec
    services.recompute_operability(truck)
    return ok_object(serializers.permit(rec), 201)


@bp.get("/health-permits")
def list_permits():
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    records = list(db.permits.values())
    truck_id = request.args.get("truck_id")
    if truck_id is not None:
        records = [r for r in records if r["truck_id"] == truck_id]
    window, total = paginate(records, limit, offset)
    return ok_array([serializers.permit(r) for r in window], limit, offset, total)


@bp.get("/health-permits/<permit_id>")
def get_permit_route(permit_id):
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    rec = get_permit(permit_id)
    return ok_object(serializers.permit(rec))


@bp.post("/health-permits/<permit_id>/revoke")
def revoke_permit(permit_id):
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    rec = get_permit(permit_id)
    if rec["status"] != "ACTIVE":
        raise err(errors.ERR_PERMIT_NOT_ACTIVE, "Permit is not ACTIVE")
    rec["status"] = "REVOKED"
    db.touch(rec)
    truck = db.trucks.get(rec["truck_id"])
    if truck is not None:
        services.recompute_operability(truck)
    return ok_object(serializers.permit(rec))
