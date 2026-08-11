"""Violation endpoints: file, read, list, uphold, dismiss — with the
points -> standing -> registration -> route-pass cascade of PRD §3.9."""
from flask import Blueprint, request

import db
from db import touch
from errors import err_not_found, err_invalid_state
from middleware import get_caller, require_role, check_holder_ownership
from response import ok_object, ok_list
from services import validate as v
from services import engine
from services.serializers import base_entity, violation_view

bp = Blueprint("violations", __name__)

READ_ROLES = ["PlatformAdmin", "CommunityAdmin", "EnforcementOfficer", "PermitHolder"]
LIST_ROLES = ["PlatformAdmin", "CommunityAdmin", "EnforcementOfficer"]
OFFICER_ROLES = ["EnforcementOfficer"]

VIOLATION_CODES = {"UNDERAGE_DRIVER", "UNREGISTERED_VEHICLE", "EQUIPMENT_MISSING",
                   "OFF_ROUTE", "PARKING_VIOLATION", "UNINSURED_OPERATION"}


@bp.post("/api/violations")
def create_violation():
    data = v.body()
    holder_id = v.require_str(data, "holder_id")
    registration_id = v.optional_str(data, "registration_id")
    code = v.require_enum(data, "violation_code", VIOLATION_CODES)
    points = v.require_int(data, "points_assessed", 1, 12)
    fine = v.require_int(data, "fine_cents", 0, None)
    occurred_at = v.require_datetime(data, "occurred_at")
    caller = get_caller()
    require_role(caller, OFFICER_ROLES)
    # Stage 4: body FKs in declared order (holder_id, registration_id?)
    holder = db.permit_holders.get(holder_id)
    if holder is None:
        raise err_not_found("PermitHolder not found")
    if registration_id is not None:
        reg = db.registrations.get(registration_id)
        if reg is None:
            raise err_not_found("Registration not found")

    vio = base_entity()
    vio.update({
        "holder_id": holder_id,
        "registration_id": registration_id,
        "violation_code": code,
        "points_assessed": points,
        "fine_cents": fine,
        "occurred_at": occurred_at,
        "status": "FILED",
    })
    db.violations[vio["id"]] = vio
    return ok_object(violation_view(vio), 201)


@bp.get("/api/violations/<vid>")
def get_violation(vid):
    caller = get_caller()
    require_role(caller, READ_ROLES)
    vio = db.violations.get(vid)
    if vio is None:
        raise err_not_found("Violation not found")
    check_holder_ownership(caller, vio["holder_id"])
    return ok_object(violation_view(vio))


@bp.get("/api/violations")
def list_violations():
    caller = get_caller()
    require_role(caller, LIST_ROLES)
    limit, offset = v.pagination_args()
    holder_id = request.args.get("holder_id")
    registration_id = request.args.get("registration_id")
    rows = list(db.violations.values())
    if holder_id is not None:
        rows = [x for x in rows if x["holder_id"] == holder_id]
    if registration_id is not None:
        rows = [x for x in rows if x["registration_id"] == registration_id]
    rows = v.sorted_by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([violation_view(x) for x in page], limit, offset, total)


@bp.post("/api/violations/<vid>/uphold")
def uphold_violation(vid):
    caller = get_caller()
    require_role(caller, OFFICER_ROLES)
    vio = db.violations.get(vid)
    if vio is None:
        raise err_not_found("Violation not found")
    if vio["status"] != "FILED":
        raise err_invalid_state("Violation is not FILED")
    vio["status"] = "UPHELD"
    touch(vio)
    holder = db.permit_holders.get(vio["holder_id"])
    engine.recompute_holder_standing(holder)
    return ok_object(violation_view(vio))


@bp.post("/api/violations/<vid>/dismiss")
def dismiss_violation(vid):
    caller = get_caller()
    require_role(caller, OFFICER_ROLES)
    vio = db.violations.get(vid)
    if vio is None:
        raise err_not_found("Violation not found")
    if vio["status"] not in ("FILED", "UPHELD"):
        raise err_invalid_state("Violation is not FILED or UPHELD")
    was_upheld = vio["status"] == "UPHELD"
    vio["status"] = "DISMISSED"
    touch(vio)
    if was_upheld:
        holder = db.permit_holders.get(vio["holder_id"])
        engine.recompute_holder_standing(holder)
    return ok_object(violation_view(vio))
