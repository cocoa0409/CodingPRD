"""Inspection endpoints (PRD 3.5, 3.6): type-gated scheduling, buffered
inspector conflicts, result recording with the annual-fail revocation cascade."""

from flask import Blueprint, g

import db
from errors import (
    ApiError, ERR_DEFICIENCY_CODES_REQUIRED, ERR_INSPECTION_NOT_FOUND,
    ERR_INSPECTION_NOT_STARTED, ERR_INSPECTION_STATE_FORBIDS,
    ERR_INSPECTOR_BUFFER_CONFLICT, ERR_INSPECTOR_NOT_INDEPENDENT,
    ERR_INVALID_DATE_RANGE, ERR_NOT_ASSIGNED_INSPECTOR,
    ERR_PROJECT_NOT_FOUND, ERR_PROJECT_STATE_FORBIDS,
    ERR_REINSPECTION_NOT_APPLICABLE, ERR_TECHNICIAN_NOT_ACTIVE,
    ERR_TECHNICIAN_NOT_CERTIFIED, ERR_TECHNICIAN_NOT_FOUND,
    ERR_UNIT_NOT_FOUND, ERR_UNIT_NOT_IN_SERVICE, invalid_request,
    state_forbids,
)
from middleware import INSPECTOR, PROJECT_COORDINATOR, ALL_ROLES, require_roles
from response import ok
from routes.common import get_or_404, list_endpoint
from services import calc, cascade
from util import get_json_body, serialize, validate_body

bp = Blueprint("inspections", __name__)

INSPECTION_TYPES = ["ACCEPTANCE", "ANNUAL", "REINSPECTION", "MODERNIZATION_ACCEPTANCE"]
QEI_LEVEL = ("QEI", "CET_AND_QEI")

CREATE_SPEC = {
    "unit_id": ("string", True, None),
    "project_id": ("string", False, None),
    "inspector_technician_id": ("string", True, None),
    "inspection_type": ("enum", True, INSPECTION_TYPES),
    "scheduled_start": ("datetime", True, None),
    "scheduled_end": ("datetime", True, None),
}

PROJECT_TYPES = ("ACCEPTANCE", "MODERNIZATION_ACCEPTANCE")


def _latest_terminal_inspection(unit_id):
    """Latest terminal (PASSED/FAILED) inspection on the unit."""
    terminal = [
        i for i in db.inspections.values()
        if i["unit_id"] == unit_id and i["status"] in ("PASSED", "FAILED")
    ]
    if not terminal:
        return None
    terminal.sort(key=lambda i: (i["recorded_at"], i["_seq"]))
    return terminal[-1]


@bp.post("/api/inspections")
@require_roles(PROJECT_COORDINATOR)
def create_inspection():
    vals = validate_body(get_json_body(), CREATE_SPEC)
    itype = vals["inspection_type"]
    if itype in PROJECT_TYPES and "project_id" not in vals:
        raise invalid_request(f"project_id is required for {itype} inspections")
    if itype not in PROJECT_TYPES and "project_id" in vals:
        raise invalid_request(f"project_id is forbidden for {itype} inspections")
    # body foreign keys (priority 4)
    unit = get_or_404(db.units, vals["unit_id"], ERR_UNIT_NOT_FOUND, "Unit")
    project = None
    if "project_id" in vals:
        project = get_or_404(db.projects, vals["project_id"], ERR_PROJECT_NOT_FOUND, "Project")
    inspector = get_or_404(db.technicians, vals["inspector_technician_id"], ERR_TECHNICIAN_NOT_FOUND, "Technician")
    # creation-time type gates (priority 5)
    if itype in PROJECT_TYPES:
        if project["status"] != "INSTALL_COMPLETE":
            raise state_forbids(ERR_PROJECT_STATE_FORBIDS, "Project")
    elif itype == "ANNUAL":
        if unit["equipment_status"] != "IN_SERVICE":
            raise ApiError(ERR_UNIT_NOT_IN_SERVICE, 409, "ANNUAL inspection requires the unit to be IN_SERVICE")
    elif itype == "REINSPECTION":
        latest = _latest_terminal_inspection(unit["id"])
        if latest is None or latest["status"] != "FAILED":
            raise ApiError(ERR_REINSPECTION_NOT_APPLICABLE, 409, "REINSPECTION requires the unit's latest terminal inspection to be FAILED")
    # certification (priority 6): inspector must hold QEI-level certification
    if inspector["certification"] not in QEI_LEVEL:
        raise ApiError(ERR_TECHNICIAN_NOT_CERTIFIED, 403, "Inspector must hold QEI-level certification")
    # independence (priority 7): inspector must differ from the project lead installer
    if project is not None and inspector["id"] == project.get("lead_installer_technician_id"):
        raise ApiError(ERR_INSPECTOR_NOT_INDEPENDENT, 403, "Inspector must differ from the project's lead installer")
    # referenced technician must be ACTIVE (priority 8)
    if inspector["status"] != "ACTIVE":
        raise ApiError(ERR_TECHNICIAN_NOT_ACTIVE, 409, "Referenced technician is INACTIVE")
    # uniqueness/overlap (priority 9): 45-minute buffered inspector conflict
    for other in db.inspections.values():
        if other["inspector_technician_id"] != inspector["id"] or other["status"] != "SCHEDULED":
            continue
        if calc.inspector_buffer_conflict(
            vals["scheduled_start"], vals["scheduled_end"],
            other["scheduled_start"], other["scheduled_end"],
        ):
            raise ApiError(ERR_INSPECTOR_BUFFER_CONFLICT, 409, "Inspection window within 45 minutes of another SCHEDULED inspection for this inspector")
    # temporal (priority 10)
    if vals["scheduled_end"] <= vals["scheduled_start"]:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422, "scheduled_end must be strictly after scheduled_start")
    rec = db.new_record({
        "unit_id": unit["id"],
        "project_id": vals.get("project_id"),
        "inspector_technician_id": inspector["id"],
        "inspection_type": itype,
        "scheduled_start": vals["scheduled_start"],
        "scheduled_end": vals["scheduled_end"],
        "deficiency_codes": [],
        "recorded_at": None,
        "status": "SCHEDULED",
    })
    db.inspections[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/api/inspections")
@require_roles(*ALL_ROLES)
def list_inspections():
    return list_endpoint(db.inspections, {
        "unit_id": "unit_id",
        "project_id": "project_id",
        "inspector_technician_id": "inspector_technician_id",
        "inspection_type": "inspection_type",
        "status": "status",
    })


@bp.get("/api/inspections/<inspectionId>")
@require_roles(*ALL_ROLES)
def get_inspection(inspectionId):
    rec = get_or_404(db.inspections, inspectionId, ERR_INSPECTION_NOT_FOUND, "Inspection")
    return ok(serialize(rec))


def _normalize_result(raw):
    if isinstance(raw, str):
        low = raw.lower()
        if low in ("pass", "passed"):
            return "PASSED"
        if low in ("fail", "failed"):
            return "FAILED"
    raise invalid_request("Field 'result' must be 'pass' or 'fail'")


@bp.post("/api/inspections/<inspectionId>/record-result")
@require_roles(INSPECTOR)
def record_result(inspectionId):
    insp = get_or_404(db.inspections, inspectionId, ERR_INSPECTION_NOT_FOUND, "Inspection")
    body = get_json_body()
    vals = validate_body(body, {
        "result": ("string", True, None),
        "deficiency_codes": ("string_array", False, None),
    })
    result = _normalize_result(vals["result"])
    # state admission (priority 5)
    if insp["status"] != "SCHEDULED":
        raise state_forbids(ERR_INSPECTION_STATE_FORBIDS, "Inspection")
    # identity binding (priority 7): only the assigned inspector
    if g.user_id != insp["inspector_technician_id"]:
        raise ApiError(ERR_NOT_ASSIGNED_INSPECTOR, 403, "Caller is not the assigned inspector")
    # temporal (priority 10): not before scheduled_start
    if db.now() < insp["scheduled_start"]:
        raise ApiError(ERR_INSPECTION_NOT_STARTED, 409, "Inspection has not started")
    if result == "FAILED" and not vals.get("deficiency_codes"):
        raise ApiError(ERR_DEFICIENCY_CODES_REQUIRED, 422, "A FAILED result requires a non-empty deficiency_codes array")
    insp["recorded_at"] = db.now()
    insp["status"] = result
    insp["deficiency_codes"] = vals.get("deficiency_codes", []) if result == "FAILED" else []
    db.touch(insp)
    unit = db.units.get(insp["unit_id"])
    project = db.projects.get(insp["project_id"]) if insp.get("project_id") else None
    if result == "PASSED" and insp["inspection_type"] in PROJECT_TYPES:
        # project INSTALL_COMPLETE -> AWAITING_REGISTRATION
        if project is not None and project["status"] == "INSTALL_COMPLETE":
            project["status"] = "AWAITING_REGISTRATION"
            db.touch(project)
        if insp["inspection_type"] == "MODERNIZATION_ACCEPTANCE" and project is not None:
            # replaced unit UNDER_MODERNIZATION -> DECOMMISSIONED; replacement stays INSTALLED
            old_id = project.get("modernize_unit_id")
            old_unit = db.units.get(old_id) if old_id else None
            if old_unit is not None and old_unit["equipment_status"] == "UNDER_MODERNIZATION":
                cascade.decommission_unit(old_unit)
    elif result == "FAILED" and insp["inspection_type"] == "ANNUAL" and unit is not None:
        # four-hop revocation cascade
        for cert in db.certificates.values():
            if cert["unit_id"] == unit["id"] and cert["status"] in ("ACTIVE", "RENEWAL_DUE"):
                cert["status"] = "REVOKED"
                db.touch(cert)
        if unit["registration_status"] == "REGISTERED":
            unit["registration_status"] = "SUSPENDED"
        if unit["equipment_status"] == "IN_SERVICE":
            unit["equipment_status"] = "OUT_OF_SERVICE"
        db.touch(unit)
        cascade.unit_out_of_service(unit)
    return ok(serialize(insp))


@bp.post("/api/inspections/<inspectionId>/cancel")
@require_roles(PROJECT_COORDINATOR)
def cancel_inspection(inspectionId):
    insp = get_or_404(db.inspections, inspectionId, ERR_INSPECTION_NOT_FOUND, "Inspection")
    if insp["status"] != "SCHEDULED":
        raise state_forbids(ERR_INSPECTION_STATE_FORBIDS, "Inspection")
    insp["status"] = "CANCELLED"
    db.touch(insp)
    return ok(serialize(insp))
