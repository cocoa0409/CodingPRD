import uuid
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
import util
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_UNIT_OVERLAP_BUFFER,
    ERR_UNIT_CAPABILITY_MISMATCH, ERR_WINDOW_NOT_ACTIVE,
)
from helpers import (
    body_dict, req_str, req_dt, get_or_404, serialize, serialize_list, paginate,
)
from middleware import authenticate, ALL_ROLES
from response import success
from services import calc
from services import workflow
from util import dec as dec_num

bp = Blueprint("assignments", __name__)

BUFFER = timedelta(hours=4)


@bp.post("/cable-diagnostics/equipment-assignments")
def create_assignment():
    authenticate(["DispatchCoordinator"])
    body = body_dict()
    mobile_unit_id = req_str(body, "mobile_unit_id")
    test_job_id = req_str(body, "test_job_id")
    mobilize_at = req_dt(body, "mobilize_at")
    demobilize_at = req_dt(body, "demobilize_at")
    if demobilize_at <= mobilize_at:
        raise ApiError(ERR_INVALID_REQUEST, 400, "demobilize_at must be strictly after mobilize_at")

    unit = get_or_404(db.units, mobile_unit_id, "MobileUnit")
    job = get_or_404(db.jobs, test_job_id, "TestJob")

    if unit["status"] == "MAINTENANCE":
        raise ApiError(ERR_INVALID_STATE, 409, "Unit is in MAINTENANCE")
    if job["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise ApiError(ERR_INVALID_STATE, 409, "Job must be PLANNED or IN_PROGRESS")

    for a in db.assignments.values():
        if a["mobile_unit_id"] != mobile_unit_id or a["status"] not in workflow.OPEN_ASSIGNMENT_STATES:
            continue
        if mobilize_at >= a["demobilize_at"] + BUFFER:
            continue
        if a["mobilize_at"] >= demobilize_at + BUFFER:
            continue
        raise ApiError(ERR_UNIT_OVERLAP_BUFFER, 409, "Assignment violates the 4h inter-assignment buffer")

    needed = set()
    for m in job["requested_methods"]:
        needed |= calc.METHOD_CAPABILITY[m]
    if not needed <= set(unit["capabilities"]):
        raise ApiError(ERR_UNIT_CAPABILITY_MISMATCH, 409, "Unit capabilities do not cover the job methods")
    circuit = db.circuits[job["circuit_id"]]
    required_kv = Decimal("1.5") * calc.U0_KV[circuit["voltage_class"]]
    if dec_num(unit["max_test_voltage_kv"]) < required_kv:
        raise ApiError(ERR_UNIT_CAPABILITY_MISMATCH, 409, "Unit voltage ceiling below 1.5 x U0")

    now = db.now()
    duration = util.rhu(util.hours_between(mobilize_at, demobilize_at), 1)
    rec = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "mobile_unit_id": mobile_unit_id,
        "test_job_id": test_job_id,
        "mobilize_at": mobilize_at,
        "demobilize_at": demobilize_at,
        "duration_hours": duration,
        "status": "RESERVED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.assignments[rec["id"]] = rec
    if unit["status"] == "AVAILABLE":
        unit["status"] = "ASSIGNED"
    workflow.settle_unit(unit)
    return success(serialize(rec), code=201)


@bp.get("/cable-diagnostics/equipment-assignments/<aid>")
def get_assignment(aid):
    authenticate(ALL_ROLES)
    rec = get_or_404(db.assignments, aid, "EquipmentAssignment")
    return success(serialize(rec))


@bp.get("/cable-diagnostics/equipment-assignments")
def list_assignments():
    authenticate(ALL_ROLES)
    recs = list(db.assignments.values())
    unit_id = request.args.get("mobile_unit_id")
    if unit_id is not None:
        recs = [a for a in recs if a["mobile_unit_id"] == unit_id]
    job_id = request.args.get("test_job_id")
    if job_id is not None:
        recs = [a for a in recs if a["test_job_id"] == job_id]
    status = request.args.get("status")
    if status is not None:
        recs = [a for a in recs if a["status"] == status]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.post("/cable-diagnostics/equipment-assignments/<aid>/confirm")
def confirm_assignment(aid):
    authenticate(["DispatchCoordinator"])
    rec = get_or_404(db.assignments, aid, "EquipmentAssignment")
    if rec["status"] != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a RESERVED assignment can be confirmed")
    rec["status"] = "CONFIRMED"
    workflow.touch(rec)
    return success(serialize(rec))


@bp.post("/cable-diagnostics/equipment-assignments/<aid>/activate")
def activate_assignment(aid):
    authenticate(["DispatchCoordinator"])
    rec = get_or_404(db.assignments, aid, "EquipmentAssignment")
    if rec["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a CONFIRMED assignment can be activated")
    if db.now() < rec["mobilize_at"]:
        raise ApiError(ERR_WINDOW_NOT_ACTIVE, 409, "mobilize_at has not been reached")
    rec["status"] = "ACTIVE"
    workflow.touch(rec)
    return success(serialize(rec))


@bp.post("/cable-diagnostics/equipment-assignments/<aid>/release")
def release_assignment(aid):
    authenticate(["DispatchCoordinator"])
    rec = get_or_404(db.assignments, aid, "EquipmentAssignment")
    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE assignment can be released")
    workflow.release_assignment(rec)
    return success(serialize(rec))


@bp.post("/cable-diagnostics/equipment-assignments/<aid>/cancel")
def cancel_assignment(aid):
    authenticate(["DispatchCoordinator"])
    rec = get_or_404(db.assignments, aid, "EquipmentAssignment")
    if rec["status"] not in ("RESERVED", "CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only a RESERVED or CONFIRMED assignment can be cancelled")
    workflow.cancel_assignment(rec)
    return success(serialize(rec))
