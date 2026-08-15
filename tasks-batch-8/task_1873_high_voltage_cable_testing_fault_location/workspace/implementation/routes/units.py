import uuid
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_UNIT_HAS_ASSIGNMENTS,
)
from helpers import (
    body_dict, req_str, req_num, req_list, get_or_404, serialize,
    serialize_list, paginate,
)
from middleware import authenticate, ALL_ROLES
from response import success
from services import calc
from services import workflow
from util import dec as dec_num

bp = Blueprint("units", __name__)


@bp.post("/cable-diagnostics/mobile-units")
def create_unit():
    authenticate(["SystemAdmin"])
    body = body_dict()
    unit_code = req_str(body, "unit_code")
    capabilities = req_list(body, "capabilities")
    if not capabilities:
        raise ApiError(ERR_INVALID_REQUEST, 400, "capabilities must be non-empty")
    for c in capabilities:
        if c not in calc.UNIT_CAPABILITIES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "capabilities must be drawn from VLF, PD, TDR")
    max_test_voltage_kv = req_num(body, "max_test_voltage_kv")
    v = dec_num(max_test_voltage_kv)
    if v is None or v <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "max_test_voltage_kv must be > 0")
    if any(u["unit_code"] == unit_code for u in db.units.values()):
        raise ApiError(ERR_INVALID_REQUEST, 400, "unit_code already registered")
    now = db.now()
    rec = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "unit_code": unit_code,
        "capabilities": list(capabilities),
        "max_test_voltage_kv": max_test_voltage_kv,
        "status": "AVAILABLE",
        "committed_hours": Decimal("0.0"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.units[rec["id"]] = rec
    return success(serialize(rec), code=201)


@bp.get("/cable-diagnostics/mobile-units/<uid>")
def get_unit(uid):
    authenticate(ALL_ROLES)
    rec = get_or_404(db.units, uid, "MobileUnit")
    return success(serialize(rec))


@bp.get("/cable-diagnostics/mobile-units")
def list_units():
    authenticate(ALL_ROLES)
    recs = list(db.units.values())
    status = request.args.get("status")
    if status is not None:
        recs = [u for u in recs if u["status"] == status]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.post("/cable-diagnostics/mobile-units/<uid>/maintenance")
def unit_maintenance(uid):
    authenticate(["DispatchCoordinator"])
    unit = get_or_404(db.units, uid, "MobileUnit")
    if any(
        a["mobile_unit_id"] == uid and a["status"] in workflow.OPEN_ASSIGNMENT_STATES
        for a in db.assignments.values()
    ):
        raise ApiError(ERR_UNIT_HAS_ASSIGNMENTS, 409, "Unit still holds open assignments")
    if unit["status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an AVAILABLE unit can enter maintenance")
    unit["status"] = "MAINTENANCE"
    workflow.touch(unit)
    return success(serialize(unit))


@bp.post("/cable-diagnostics/mobile-units/<uid>/return-to-service")
def unit_return(uid):
    authenticate(["DispatchCoordinator"])
    unit = get_or_404(db.units, uid, "MobileUnit")
    if unit["status"] != "MAINTENANCE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a MAINTENANCE unit can return to service")
    unit["status"] = "AVAILABLE"
    workflow.touch(unit)
    return success(serialize(unit))


@bp.get("/cable-diagnostics/mobile-units/<uid>/equipment-assignments")
def unit_assignments(uid):
    authenticate(ALL_ROLES)
    get_or_404(db.units, uid, "MobileUnit")
    recs = [a for a in db.assignments.values() if a["mobile_unit_id"] == uid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)
