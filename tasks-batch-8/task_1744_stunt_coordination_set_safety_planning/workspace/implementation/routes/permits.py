"""Permit: apply, grant, deny, revoke (with cascade)."""

from flask import Blueprint, request

from db import store
from domain import (
    get_production,
    get_permit,
    gate_posture_setup_or_active,
    cascade_permit_revoked,
    serialize_permit,
    stamp_new,
    stamp_mutable,
    touch,
    PERMIT_TYPES,
    default_sort_key,
)
from errors import err, ERR_PERMIT_INVALID_STATE, ERR_INVALID_TIME_RANGE
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_nonempty_string,
    v_enum,
    v_datetime,
)
from response import ok, ok_list
from util import new_id

bp = Blueprint("permits", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]
EXEC = ["ProductionExecutive"]


@bp.post("/api/permits")
def create_permit():
    body = get_body()
    data = validate_payload(
        body,
        {
            "production_id": (v_string, True, None),
            "permit_type": (v_enum(PERMIT_TYPES), True, None),
            "jurisdiction": (v_string, True, None),
            "valid_from": (v_datetime, True, None),
            "valid_until": (v_datetime, True, None),
        },
    )
    _, role = auth()
    require_role(role, EXEC)
    prod = get_production(data["production_id"])
    gate_posture_setup_or_active(prod)
    if not data["valid_until"] > data["valid_from"]:
        raise err(ERR_INVALID_TIME_RANGE,
                  "valid_until must be after valid_from", 422)

    permit = stamp_mutable(
        stamp_new(
            {
                "id": new_id(),
                "production_id": prod["id"],
                "permit_type": data["permit_type"],
                "jurisdiction": data["jurisdiction"],
                "valid_from": data["valid_from"],
                "valid_until": data["valid_until"],
                "status": "APPLIED",
            }
        )
    )
    store.permits[permit["id"]] = permit
    return ok(serialize_permit(permit), 201)


@bp.get("/api/permits")
def list_permits():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    production_id = request.args.get("production_id")
    permit_type = request.args.get("permit_type")
    status = request.args.get("status")
    items = []
    for p in store.permits.values():
        if production_id is not None and p["production_id"] != production_id:
            continue
        if permit_type is not None and p["permit_type"] != permit_type:
            continue
        if status is not None and p["status"] != status:
            continue
        items.append(p)
    items.sort(key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_permit(p) for p in page], total, limit, offset)


@bp.get("/api/permits/<pid>")
def get_one_permit(pid):
    _, role = auth()
    require_role(role, READ_ROLES)
    permit = get_permit(pid)
    return ok(serialize_permit(permit), 200)


@bp.post("/api/permits/<pid>/grant")
def grant_permit(pid):
    body = get_body()
    validate_payload(body, {})
    _, role = auth()
    require_role(role, EXEC)
    permit = get_permit(pid)
    prod = get_production(permit["production_id"])
    gate_posture_setup_or_active(prod)
    if permit["status"] != "APPLIED":
        raise err(ERR_PERMIT_INVALID_STATE, "grant requires status APPLIED", 409)
    permit["status"] = "GRANTED"
    touch(permit)
    return ok(serialize_permit(permit), 200)


@bp.post("/api/permits/<pid>/deny")
def deny_permit(pid):
    body = get_body()
    validate_payload(body, {})
    _, role = auth()
    require_role(role, EXEC)
    permit = get_permit(pid)
    prod = get_production(permit["production_id"])
    gate_posture_setup_or_active(prod)
    if permit["status"] != "APPLIED":
        raise err(ERR_PERMIT_INVALID_STATE, "deny requires status APPLIED", 409)
    permit["status"] = "DENIED"
    touch(permit)
    return ok(serialize_permit(permit), 200)


@bp.post("/api/permits/<pid>/revoke")
def revoke_permit(pid):
    body = get_body()
    data = validate_payload(body, {"reason": (v_nonempty_string, True, None)})
    _, role = auth()
    require_role(role, ["SafetyOfficer"])
    permit = get_permit(pid)
    if permit["status"] != "GRANTED":
        raise err(ERR_PERMIT_INVALID_STATE, "revoke requires status GRANTED", 409)
    permit["status"] = "REVOKED"
    touch(permit)
    cascade_permit_revoked(permit)
    return ok(serialize_permit(permit), 200)
