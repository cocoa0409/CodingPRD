"""QualityInspection endpoints (PRD section 3.9)."""

from flask import Blueprint

import calc
from db import store, new_entity, touch, public, fmt_ts
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_ENUM,
    ERR_INVALID_TIME_RANGE,
    ERR_PLANT_NOT_LICENSED,
    ERR_INVALID_STATE,
    ERR_INSPECTION_NOT_SCHEDULED,
    ERR_INSPECTION_NOT_IN_PROGRESS,
    ERR_INSPECTION_WINDOW_MISSED,
)
from middleware import authenticate, authorize
from response import success
from util import (
    body_json, req_field, as_enum, as_int, as_list, parse_ts,
    resolve_plant, resolve_inspection,
)

bp = Blueprint("inspections", __name__)

AGENCY_CODES = {"ALSC", "SPIB", "TPI", "WCLIB"}
SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
SEVERITY_DEDUCTION = {"CRITICAL": 200, "MAJOR": 100, "MINOR": 25}
INSPECTION_READ_ROLES = ["QualityAgencyInspector", "ComplianceOfficer", "QualityManager", "PlantOperator", "LabTechnician"]


@bp.route("/treatment-plants/<plantId>/inspections", methods=["POST"])
def create_inspection(plantId):
    body = body_json()
    agency_code = as_enum(req_field(body, "agency_code"), "agency_code", AGENCY_CODES)
    window_start = parse_ts(req_field(body, "inspection_window_start"), "inspection_window_start")
    window_end = parse_ts(req_field(body, "inspection_window_end"), "inspection_window_end")
    charges_in_scope = as_list(req_field(body, "charges_in_scope"), "charges_in_scope")
    for cid in charges_in_scope:
        if not isinstance(cid, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "charges_in_scope entries must be strings")
    findings_count = 0
    if "findings_count" in body and body["findings_count"] is not None:
        findings_count = as_int(body["findings_count"], "findings_count")
        if findings_count < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "findings_count must be non-negative")
    severity = as_enum(req_field(body, "severity"), "severity", SEVERITIES)
    if window_end <= window_start:
        raise ApiError(ERR_INVALID_TIME_RANGE, 400, "inspection_window_end must be > inspection_window_start")
    _, role = authenticate()
    authorize(role, ["QualityAgencyInspector", "ComplianceOfficer"])
    plant = resolve_plant(plantId)
    insp = new_entity()
    insp.update({
        "plant_id": plant["id"],
        "agency_code": agency_code,
        "inspection_window_start": fmt_ts(window_start),
        "inspection_window_end": fmt_ts(window_end),
        "charges_in_scope": list(charges_in_scope),
        "findings_count": findings_count,
        "severity": severity,
        "status": "SCHEDULED",
        "_start_dt": window_start,
        "_end_dt": window_end,
    })
    store.inspections[insp["id"]] = insp
    return success(public(insp), status=201)


@bp.route("/treatment-plants/<plantId>/inspections/<inspectionId>", methods=["GET"])
def get_inspection(plantId, inspectionId):
    _, role = authenticate()
    authorize(role, INSPECTION_READ_ROLES)
    plant = resolve_plant(plantId)
    return success(public(resolve_inspection(inspectionId, plant)))


@bp.route("/treatment-plants/<plantId>/inspections/<inspectionId>/begin", methods=["POST"])
def begin_inspection(plantId, inspectionId):
    _, role = authenticate()
    authorize(role, ["QualityAgencyInspector"])
    plant = resolve_plant(plantId)
    insp = resolve_inspection(inspectionId, plant)
    # Plant licensing: a SUSPENDED plant's inspections cannot move IN_PROGRESS.
    if plant["status"] != "LICENSED":
        raise ApiError(ERR_PLANT_NOT_LICENSED, 409, "Inspection begin requires plant status LICENSED")
    if insp["status"] != "SCHEDULED":
        raise ApiError(ERR_INSPECTION_NOT_SCHEDULED, 409, "Begin requires inspection status SCHEDULED")
    now = store.clock
    if not (insp["_start_dt"] <= now <= insp["_end_dt"]):
        raise ApiError(ERR_INSPECTION_WINDOW_MISSED, 409, "now is outside [inspection_window_start, inspection_window_end]")
    insp["status"] = "IN_PROGRESS"
    touch(insp)
    return success(public(insp))


@bp.route("/treatment-plants/<plantId>/inspections/<inspectionId>/issue-findings", methods=["POST"])
def issue_findings(plantId, inspectionId):
    body = body_json()
    findings_count = as_int(req_field(body, "findings_count"), "findings_count")
    if findings_count < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "findings_count must be non-negative")
    severity = as_enum(req_field(body, "severity"), "severity", SEVERITIES)
    _, role = authenticate()
    authorize(role, ["QualityAgencyInspector"])
    plant = resolve_plant(plantId)
    insp = resolve_inspection(inspectionId, plant)
    if insp["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INSPECTION_NOT_IN_PROGRESS, 409, "issue-findings requires inspection status IN_PROGRESS")
    insp["findings_count"] = findings_count
    insp["severity"] = severity
    insp["status"] = "FINDINGS_ISSUED"
    touch(insp)
    plant["compliance_score"] = calc.clamp_score(plant["compliance_score"] - SEVERITY_DEDUCTION[severity])
    touch(plant)
    return success(public(insp))


@bp.route("/treatment-plants/<plantId>/inspections/<inspectionId>/close", methods=["POST"])
def close_inspection(plantId, inspectionId):
    body = body_json()
    outcome = req_field(body, "outcome")
    if not isinstance(outcome, str) or outcome not in ("PASS", "FAIL", "CLOSED_PASS", "CLOSED_FAIL"):
        raise ApiError(ERR_INVALID_ENUM, 400, "outcome must be PASS or FAIL")
    _, role = authenticate()
    authorize(role, ["QualityAgencyInspector"])
    plant = resolve_plant(plantId)
    insp = resolve_inspection(inspectionId, plant)
    if insp["status"] != "FINDINGS_ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "Close requires inspection status FINDINGS_ISSUED")
    passed = outcome in ("PASS", "CLOSED_PASS")
    insp["status"] = "CLOSED_PASS" if passed else "CLOSED_FAIL"
    touch(insp)
    if not passed and plant["compliance_score"] <= calc.SUSPEND_THRESHOLD and plant["status"] == "LICENSED":
        plant["status"] = "SUSPENDED"
        touch(plant)
    return success(public(insp))
