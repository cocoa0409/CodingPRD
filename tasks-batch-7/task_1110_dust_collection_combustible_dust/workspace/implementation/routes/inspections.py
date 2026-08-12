"""Inspection and InspectionFinding endpoints."""
from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from middleware import require_roles
from response import success_object
from services import calculations as calc
from services.common import (
    get_flat_or_404,
    get_site_or_404,
    init_common,
    paginate,
    parse_body,
    parse_iso,
    require_fields,
    serialize,
    touch,
    validate_enum,
    validate_str,
)

bp = Blueprint("inspections", __name__)

READ_ROLES = ("InspectorUser", "ComplianceManager", "ComplianceEngineer")
INSPECTOR_KINDS = {"AHJ", "INSURER", "INTERNAL"}
SEVERITIES = {"OBSERVATION", "MINOR", "MAJOR", "CRITICAL"}


def _get_inspection(site_id, inspection_id):
    site = get_site_or_404(site_id)
    insp = db.inspections.get(inspection_id)
    if insp is None or insp["site_id"] != site["id"]:
        raise ApiError(ERR_NOT_FOUND, f"Inspection {inspection_id} not found", 404)
    return site, insp


def _get_finding(site_id, inspection_id, finding_id):
    site, insp = _get_inspection(site_id, inspection_id)
    finding = db.inspection_findings.get(finding_id)
    if finding is None or finding["inspection_id"] != insp["id"]:
        raise ApiError(ERR_NOT_FOUND, f"InspectionFinding {finding_id} not found", 404)
    return site, insp, finding


@bp.route("/api/sites/<id>/inspections", methods=["POST"])
def create_inspection(id):
    require_roles("InspectorUser")
    site = get_site_or_404(id)
    body = parse_body()
    require_fields(body, ["inspector_kind", "inspector_ref", "conducted_at"])
    validate_enum(body, "inspector_kind", INSPECTOR_KINDS)
    validate_str(body, "inspector_ref")
    conducted = parse_iso(body["conducted_at"], "conducted_at")

    insp = {
        "site_id": site["id"],
        "inspector_kind": body["inspector_kind"],
        "inspector_ref": body["inspector_ref"],
        "conducted_at": db.iso(conducted),
        "conducted_at_dt": conducted,
        "status": "OPEN",
    }
    init_common(insp)
    db.inspections[insp["id"]] = insp
    return success_object(serialize(insp), 201)


@bp.route("/api/sites/<id>/inspections", methods=["GET"])
def list_inspections(id):
    require_roles(*READ_ROLES)
    site = get_site_or_404(id)
    items = [i for i in db.inspections.values() if i["site_id"] == site["id"]]
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = "status"
    if request.args.get("inspector_kind") is not None:
        filters["inspector_kind"] = "inspector_kind"
    return paginate(items, filters)


@bp.route("/api/sites/<id>/inspections/<inspection_id>", methods=["GET"])
def get_inspection(id, inspection_id):
    require_roles(*READ_ROLES)
    _, insp = _get_inspection(id, inspection_id)
    return success_object(serialize(insp), 200)


@bp.route("/api/sites/<id>/inspections/<inspection_id>/submit", methods=["POST"])
def submit_inspection(id, inspection_id):
    require_roles("InspectorUser")
    _, insp = _get_inspection(id, inspection_id)
    if insp["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "Inspection is not OPEN", 409)
    insp["status"] = "SUBMITTED"
    touch(insp)
    return success_object(serialize(insp), 200)


@bp.route("/api/sites/<id>/inspections/<inspection_id>/accept", methods=["POST"])
def accept_inspection(id, inspection_id):
    require_roles("ComplianceManager")
    site, insp = _get_inspection(id, inspection_id)
    if insp["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Inspection is not SUBMITTED", 409)
    for finding in db.inspection_findings.values():
        if finding["inspection_id"] == insp["id"] and finding["status"] not in ("VERIFIED", "WITHDRAWN"):
            raise ApiError(ERR_INVALID_STATE, "Not all findings are VERIFIED or WITHDRAWN", 409)
    insp["status"] = "ACCEPTED"
    touch(insp)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(insp), 200)


@bp.route("/api/sites/<id>/inspections/<inspection_id>/reject", methods=["POST"])
def reject_inspection(id, inspection_id):
    require_roles("ComplianceManager")
    site, insp = _get_inspection(id, inspection_id)
    if insp["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Inspection is not SUBMITTED", 409)
    insp["status"] = "REJECTED"
    touch(insp)
    for finding in db.inspection_findings.values():
        if finding["inspection_id"] == insp["id"] and finding["status"] in ("OPEN", "IN_PROGRESS"):
            if finding["severity"] == "CRITICAL" and finding["status"] == "OPEN":
                site["open_critical_findings"] = max(
                    0, int(site.get("open_critical_findings", 0)) - 1
                )
            finding["status"] = "DISPUTED"
            touch(finding)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(insp), 200)


# ----- Findings -----
@bp.route("/api/sites/<id>/inspections/<inspection_id>/findings", methods=["POST"])
def create_finding(id, inspection_id):
    require_roles("InspectorUser")
    site, insp = _get_inspection(id, inspection_id)
    body = parse_body()
    require_fields(body, ["severity", "description", "due_at"])
    validate_enum(body, "severity", SEVERITIES)
    validate_str(body, "description")
    due = parse_iso(body["due_at"], "due_at")

    collector_id = body.get("collector_id")
    if collector_id is not None:
        col = db.collectors.get(collector_id)
        if col is None or col["site_id"] != site["id"]:
            raise ApiError(ERR_NOT_FOUND, f"Collector {collector_id} not found", 404)

    finding = {
        "inspection_id": insp["id"],
        "collector_id": collector_id,
        "severity": body["severity"],
        "description": body["description"],
        "due_at": db.iso(due),
        "due_at_dt": due,
        "status": "OPEN",
    }
    init_common(finding)
    db.inspection_findings[finding["id"]] = finding
    if finding["severity"] == "CRITICAL":
        site["open_critical_findings"] = int(site.get("open_critical_findings", 0)) + 1
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(finding), 201)


@bp.route("/api/sites/<id>/inspections/<inspection_id>/findings", methods=["GET"])
def list_findings(id, inspection_id):
    require_roles(*READ_ROLES)
    _, insp = _get_inspection(id, inspection_id)
    items = [f for f in db.inspection_findings.values() if f["inspection_id"] == insp["id"]]
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = "status"
    if request.args.get("severity") is not None:
        filters["severity"] = "severity"
    if request.args.get("collector_id") is not None:
        filters["collector_id"] = "collector_id"
    return paginate(items, filters)


@bp.route("/api/sites/<id>/inspections/<inspection_id>/findings/<finding_id>", methods=["GET"])
def get_finding(id, inspection_id, finding_id):
    require_roles(*READ_ROLES)
    _, _, finding = _get_finding(id, inspection_id, finding_id)
    return success_object(serialize(finding), 200)


def _critical_bump(site, finding, delta):
    if finding["severity"] == "CRITICAL":
        site["open_critical_findings"] = max(
            0, int(site.get("open_critical_findings", 0)) + delta
        )


@bp.route("/api/sites/<id>/inspections/<inspection_id>/findings/<finding_id>/start_work", methods=["POST"])
def start_work(id, inspection_id, finding_id):
    require_roles("ComplianceEngineer")
    _, _, finding = _get_finding(id, inspection_id, finding_id)
    if finding["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_INVALID_STATE, "Finding is not OPEN or REOPENED", 409)
    finding["status"] = "IN_PROGRESS"
    touch(finding)
    return success_object(serialize(finding), 200)


@bp.route("/api/sites/<id>/inspections/<inspection_id>/findings/<finding_id>/resolve", methods=["POST"])
def resolve_finding(id, inspection_id, finding_id):
    require_roles("ComplianceEngineer")
    site, _, finding = _get_finding(id, inspection_id, finding_id)
    if finding["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, "Finding is not IN_PROGRESS", 409)
    finding["status"] = "RESOLVED"
    touch(finding)
    _critical_bump(site, finding, -1)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(finding), 200)


@bp.route("/api/sites/<id>/inspections/<inspection_id>/findings/<finding_id>/verify", methods=["POST"])
def verify_finding(id, inspection_id, finding_id):
    require_roles("ComplianceManager")
    _, _, finding = _get_finding(id, inspection_id, finding_id)
    if finding["status"] != "RESOLVED":
        raise ApiError(ERR_INVALID_STATE, "Finding is not RESOLVED", 409)
    finding["status"] = "VERIFIED"
    touch(finding)
    return success_object(serialize(finding), 200)


@bp.route("/api/sites/<id>/inspections/<inspection_id>/findings/<finding_id>/reopen", methods=["POST"])
def reopen_finding(id, inspection_id, finding_id):
    require_roles("ComplianceManager")
    site, _, finding = _get_finding(id, inspection_id, finding_id)
    if finding["status"] != "RESOLVED":
        raise ApiError(ERR_INVALID_STATE, "Finding is not RESOLVED", 409)
    finding["status"] = "REOPENED"
    touch(finding)
    _critical_bump(site, finding, +1)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(finding), 200)


@bp.route("/api/sites/<id>/inspections/<inspection_id>/findings/<finding_id>/dispute", methods=["POST"])
def dispute_finding(id, inspection_id, finding_id):
    require_roles("ComplianceEngineer")
    site, _, finding = _get_finding(id, inspection_id, finding_id)
    if finding["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "Finding is not OPEN", 409)
    finding["status"] = "DISPUTED"
    touch(finding)
    _critical_bump(site, finding, -1)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(finding), 200)


@bp.route("/api/sites/<id>/inspections/<inspection_id>/findings/<finding_id>/withdraw", methods=["POST"])
def withdraw_finding(id, inspection_id, finding_id):
    require_roles("InspectorUser")
    _, _, finding = _get_finding(id, inspection_id, finding_id)
    if finding["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, "Finding is not DISPUTED", 409)
    finding["status"] = "WITHDRAWN"
    touch(finding)
    return success_object(serialize(finding), 200)


# ----- Flat endpoints -----
@bp.route("/api/inspections/<id>", methods=["GET"])
def get_inspection_flat(id):
    require_roles(*READ_ROLES)
    insp = get_flat_or_404(db.inspections, id, "Inspection")
    return success_object(serialize(insp), 200)


@bp.route("/api/inspections/<id>/findings", methods=["GET"])
def list_inspection_findings_flat(id):
    require_roles(*READ_ROLES)
    insp = get_flat_or_404(db.inspections, id, "Inspection")
    items = [f for f in db.inspection_findings.values() if f["inspection_id"] == insp["id"]]
    return paginate(items)


@bp.route("/api/inspection-findings/<id>", methods=["GET"])
def get_finding_flat(id):
    require_roles(*READ_ROLES)
    finding = get_flat_or_404(db.inspection_findings, id, "InspectionFinding")
    return success_object(serialize(finding), 200)


@bp.route("/api/inspection-findings/<id>/retrofit-projects", methods=["GET"])
def list_finding_retrofit_projects(id):
    require_roles("ComplianceEngineer", "ComplianceManager", "InspectorUser")
    finding = get_flat_or_404(db.inspection_findings, id, "InspectionFinding")
    items = [p for p in db.retrofit_projects.values() if p.get("trigger_finding_id") == finding["id"]]
    return paginate(items)
