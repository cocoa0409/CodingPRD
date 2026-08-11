"""Incident and CAPAAction endpoints."""
from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CAPA_OPEN,
    ERR_CAPA_REQUIRED,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_ROOT_CAUSE_REQUIRED,
    ERR_SOD_VIOLATION,
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

bp = Blueprint("incidents", __name__)

READ_ROLES = ("ComplianceManager", "ComplianceEngineer", "IncidentInvestigator",
              "SafetyManager", "InspectorUser")
KINDS = {"FIRE", "DEFLAGRATION", "EMBER_RELEASE", "NEAR_MISS"}
SEVERITIES = {"MINOR", "MAJOR", "CATASTROPHIC"}
ROOT_CAUSES = {"HOUSEKEEPING", "HOT_WORK", "EQUIPMENT_FAILURE", "STATIC_DISCHARGE", "UNKNOWN"}


def _get_incident(site_id, incident_id):
    site = get_site_or_404(site_id)
    inc = db.incidents.get(incident_id)
    if inc is None or inc["site_id"] != site["id"]:
        raise ApiError(ERR_NOT_FOUND, f"Incident {incident_id} not found", 404)
    return site, inc


def _get_capa(site_id, incident_id, capa_id):
    site, inc = _get_incident(site_id, incident_id)
    capa = db.capa_actions.get(capa_id)
    if capa is None or capa["incident_id"] != inc["id"]:
        raise ApiError(ERR_NOT_FOUND, f"CAPAAction {capa_id} not found", 404)
    return site, inc, capa


@bp.route("/api/sites/<id>/incidents", methods=["POST"])
def create_incident(id):
    require_roles("ComplianceManager", "SafetyManager")
    site = get_site_or_404(id)
    body = parse_body()
    require_fields(body, ["occurred_at", "kind", "description", "severity",
                          "root_cause_code", "investigation_lead_id"])
    validate_enum(body, "kind", KINDS)
    validate_enum(body, "severity", SEVERITIES)
    validate_enum(body, "root_cause_code", ROOT_CAUSES)
    validate_str(body, "description")
    validate_str(body, "investigation_lead_id")
    occurred = parse_iso(body["occurred_at"], "occurred_at")

    collector_id = body.get("collector_id")
    if collector_id is not None:
        col = db.collectors.get(collector_id)
        if col is None or col["site_id"] != site["id"]:
            raise ApiError(ERR_NOT_FOUND, f"Collector {collector_id} not found", 404)

    inc = {
        "site_id": site["id"],
        "occurred_at": db.iso(occurred),
        "occurred_at_dt": occurred,
        "collector_id": collector_id,
        "kind": body["kind"],
        "description": body["description"],
        "severity": body["severity"],
        "root_cause_code": body["root_cause_code"],
        "investigation_lead_id": body["investigation_lead_id"],
        "capa_count": 0,
        "capa_open_count": 0,
        "status": "OPEN",
    }
    init_common(inc)
    db.incidents[inc["id"]] = inc
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(inc), 201)


@bp.route("/api/sites/<id>/incidents", methods=["GET"])
def list_incidents(id):
    require_roles(*READ_ROLES)
    site = get_site_or_404(id)
    items = [i for i in db.incidents.values() if i["site_id"] == site["id"]]
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = "status"
    if request.args.get("severity") is not None:
        filters["severity"] = "severity"
    if request.args.get("collector_id") is not None:
        filters["collector_id"] = "collector_id"
    return paginate(items, filters)


@bp.route("/api/sites/<id>/incidents/<incident_id>", methods=["GET"])
def get_incident(id, incident_id):
    require_roles(*READ_ROLES)
    _, inc = _get_incident(id, incident_id)
    return success_object(serialize(inc), 200)


@bp.route("/api/sites/<id>/incidents/<incident_id>/start_investigation", methods=["POST"])
def start_investigation(id, incident_id):
    user_id, _ = require_roles("IncidentInvestigator")
    site, inc = _get_incident(id, incident_id)
    if inc["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_INVALID_STATE, "Incident is not OPEN or REOPENED", 409)
    if inc["investigation_lead_id"] != user_id:
        raise ApiError(ERR_SOD_VIOLATION, "Only the assigned lead may investigate", 422)

    # SoD: lead must differ from any hot-work issuer whose permit window contains occurred_at
    if inc.get("collector_id"):
        for permit in db.hot_work_permits.values():
            if permit.get("collector_id") != inc["collector_id"]:
                continue
            if permit["issuer_id"] == user_id:
                vf, vt = permit["valid_from_dt"], permit["valid_to_dt"]
                if vf <= inc["occurred_at_dt"] < vt:
                    raise ApiError(ERR_SOD_VIOLATION,
                                   "Investigator issued a hot-work permit related to this incident", 422)

    inc["status"] = "INVESTIGATING"
    touch(inc)
    return success_object(serialize(inc), 200)


@bp.route("/api/sites/<id>/incidents/<incident_id>/define_capa", methods=["POST"])
def define_capa(id, incident_id):
    user_id, _ = require_roles("IncidentInvestigator")
    site, inc = _get_incident(id, incident_id)
    if inc["status"] != "INVESTIGATING":
        raise ApiError(ERR_INVALID_STATE, "Incident is not INVESTIGATING", 409)
    has_capa = any(c["incident_id"] == inc["id"] for c in db.capa_actions.values())
    if not has_capa:
        raise ApiError(ERR_CAPA_REQUIRED, "Incident has no CAPA actions", 422)
    if inc["root_cause_code"] == "UNKNOWN":
        raise ApiError(ERR_ROOT_CAUSE_REQUIRED, "Root cause must be determined", 422)
    inc["status"] = "CAPA_DEFINED"
    touch(inc)
    return success_object(serialize(inc), 200)


@bp.route("/api/sites/<id>/incidents/<incident_id>/close", methods=["POST"])
def close_incident(id, incident_id):
    require_roles("ComplianceManager")
    site, inc = _get_incident(id, incident_id)
    if inc["status"] != "CAPA_DEFINED":
        raise ApiError(ERR_INVALID_STATE, "Incident is not CAPA_DEFINED", 409)
    if int(inc.get("capa_open_count", 0)) != 0:
        raise ApiError(ERR_CAPA_OPEN, "Open CAPA actions remain", 422)
    inc["status"] = "CLOSED"
    touch(inc)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(inc), 200)


@bp.route("/api/sites/<id>/incidents/<incident_id>/reopen", methods=["POST"])
def reopen_incident(id, incident_id):
    require_roles("ComplianceManager")
    site, inc = _get_incident(id, incident_id)
    if inc["status"] != "CLOSED":
        raise ApiError(ERR_INVALID_STATE, "Incident is not CLOSED", 409)
    inc["status"] = "REOPENED"
    touch(inc)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(inc), 200)


# ----- CAPA actions -----
@bp.route("/api/sites/<id>/incidents/<incident_id>/capa-actions", methods=["POST"])
def create_capa(id, incident_id):
    require_roles("IncidentInvestigator")
    site, inc = _get_incident(id, incident_id)
    body = parse_body()
    require_fields(body, ["description", "owner_id", "due_at"])
    validate_str(body, "description")
    validate_str(body, "owner_id")
    due = parse_iso(body["due_at"], "due_at")

    capa = {
        "incident_id": inc["id"],
        "description": body["description"],
        "owner_id": body["owner_id"],
        "due_at": db.iso(due),
        "due_at_dt": due,
        "closed_at": None,
        "closed_at_dt": None,
        "status": "OPEN",
    }
    init_common(capa)
    db.capa_actions[capa["id"]] = capa
    inc["capa_count"] = int(inc.get("capa_count", 0)) + 1
    inc["capa_open_count"] = int(inc.get("capa_open_count", 0)) + 1
    touch(inc)
    return success_object(serialize(capa), 201)


@bp.route("/api/sites/<id>/incidents/<incident_id>/capa-actions", methods=["GET"])
def list_capas(id, incident_id):
    require_roles("IncidentInvestigator", "ComplianceManager", "ComplianceEngineer")
    site, inc = _get_incident(id, incident_id)
    items = [c for c in db.capa_actions.values() if c["incident_id"] == inc["id"]]
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = "status"
    return paginate(items, filters)


@bp.route("/api/sites/<id>/incidents/<incident_id>/capa-actions/<capa_id>/start", methods=["POST"])
def start_capa(id, incident_id, capa_id):
    user_id, _ = require_roles("IncidentInvestigator")
    site, inc, capa = _get_capa(id, incident_id, capa_id)
    if capa["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "CAPA action is not OPEN", 409)
    if capa["owner_id"] != user_id:
        raise ApiError(ERR_SOD_VIOLATION, "Only the action owner may start it", 422)
    capa["status"] = "IN_PROGRESS"
    touch(capa)
    touch(inc)
    return success_object(serialize(capa), 200)


@bp.route("/api/sites/<id>/incidents/<incident_id>/capa-actions/<capa_id>/close", methods=["POST"])
def close_capa(id, incident_id, capa_id):
    user_id, _ = require_roles("IncidentInvestigator")
    site, inc, capa = _get_capa(id, incident_id, capa_id)
    if capa["status"] not in ("IN_PROGRESS", "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE, "CAPA action cannot be closed from its current state", 409)
    if capa["owner_id"] != user_id:
        raise ApiError(ERR_SOD_VIOLATION, "Only the action owner may close it", 422)
    now = db.now_dt()
    capa["closed_at_dt"] = now
    capa["closed_at"] = db.iso(now)
    capa["status"] = "CLOSED"
    touch(capa)
    inc["capa_open_count"] = max(0, int(inc.get("capa_open_count", 0)) - 1)
    touch(inc)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(capa), 200)


# ----- Flat endpoints -----
@bp.route("/api/incidents/<id>", methods=["GET"])
def get_incident_flat(id):
    require_roles(*READ_ROLES)
    inc = get_flat_or_404(db.incidents, id, "Incident")
    return success_object(serialize(inc), 200)


@bp.route("/api/incidents/<id>/capa-actions", methods=["GET"])
def list_incident_capas_flat(id):
    require_roles("IncidentInvestigator", "ComplianceManager", "ComplianceEngineer")
    inc = get_flat_or_404(db.incidents, id, "Incident")
    items = [c for c in db.capa_actions.values() if c["incident_id"] == inc["id"]]
    return paginate(items)
