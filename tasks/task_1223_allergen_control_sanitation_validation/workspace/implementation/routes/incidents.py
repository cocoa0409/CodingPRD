from flask import Blueprint, g, request

from db import db, new_entity, public, touch
from errors import ApiError
from logic import get_or_404, recompute_posture
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from util import body, opt_str, req_enum, req_str

bp = Blueprint("incidents", __name__)

INCIDENT_TYPES = ("UNDECLARED_ALLERGEN", "LABEL_MISMATCH",
                  "SWAB_FAILURE_CLUSTER", "SUPPLIER_ALLERGEN_CHANGE",
                  "REWORK_RULE_BREACH")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def _recompute_line(incident):
    if incident["line_id"] is None:
        return
    line = db["lines"].get(incident["line_id"])
    if line is not None:
        recompute_posture(line)


@bp.post("/qa/incidents")
@require_roles("QaSupervisor", "QaManager")
def create_incident():
    b = body()
    incident_type = req_enum(b, "incident_type", INCIDENT_TYPES)
    severity = req_enum(b, "severity", SEVERITIES)
    line_id = opt_str(b, "line_id")
    product_id = opt_str(b, "product_id")
    allergen_id = opt_str(b, "allergen_id")
    if line_id is not None:
        get_or_404("lines", line_id)
    if product_id is not None:
        get_or_404("products", product_id)
    if allergen_id is not None:
        get_or_404("allergens", allergen_id)
    description = req_str(b, "description")
    ent = new_entity({
        "incident_type": incident_type,
        "severity": severity,
        "line_id": line_id,
        "product_id": product_id,
        "allergen_id": allergen_id,
        "source_label_reconciliation_id": None,
        "source_changeover_id": None,
        "description": description,
        "containment_action": None,
        "root_cause": None,
        "status": "OPEN",
        "_trigger_user_ids": [],
    })
    db["incidents"][ent["id"]] = ent
    _recompute_line(ent)
    return ok(public(ent), 201)


@bp.get("/qa/incidents")
@require_roles(*ALL_ROLES)
def list_incidents():
    items = list(db["incidents"].values())
    for param in ("line_id", "product_id", "allergen_id",
                  "source_label_reconciliation_id", "source_changeover_id",
                  "status", "severity"):
        v = request.args.get(param)
        if v is not None:
            items = [i for i in items if i.get(param) == v]
    return ok_list(items)


@bp.get("/qa/incidents/<incidentId>")
@require_roles(*ALL_ROLES)
def get_incident(incidentId):
    return ok(public(get_or_404("incidents", incidentId)))


@bp.post("/qa/incidents/<incidentId>/begin-investigation")
@require_roles("QaSupervisor")
def begin_investigation(incidentId):
    inc = get_or_404("incidents", incidentId)
    if inc["status"] != "OPEN":
        raise ApiError("ERR_INCIDENT_NOT_OPEN", 409, "Incident is not OPEN")
    inc["status"] = "INVESTIGATING"
    touch(inc)
    return ok(public(inc))


@bp.post("/qa/incidents/<incidentId>/contain")
@require_roles("QaSupervisor")
def contain_incident(incidentId):
    inc = get_or_404("incidents", incidentId)
    if inc["status"] != "INVESTIGATING":
        raise ApiError("ERR_INCIDENT_NOT_INVESTIGATING", 409,
                       "Incident is not INVESTIGATING")
    b = body()
    action = req_str(b, "containment_action")
    inc["containment_action"] = action
    inc["status"] = "CONTAINED"
    touch(inc)
    _recompute_line(inc)
    return ok(public(inc))


@bp.post("/qa/incidents/<incidentId>/close")
@require_roles("QaManager")
def close_incident(incidentId):
    inc = get_or_404("incidents", incidentId)
    if inc["status"] != "CONTAINED":
        raise ApiError("ERR_INCIDENT_NOT_CONTAINED", 409,
                       "Incident is not CONTAINED")
    b = body()
    root_cause = req_str(b, "root_cause")
    if g.user_id in inc.get("_trigger_user_ids", []):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Closer must differ from the technician who recorded the "
                       "triggering swab/label entry")
    inc["root_cause"] = root_cause
    inc["status"] = "CLOSED"
    touch(inc)
    _recompute_line(inc)
    return ok(public(inc))


@bp.post("/qa/incidents/<incidentId>/void")
@require_roles("QaManager")
def void_incident(incidentId):
    inc = get_or_404("incidents", incidentId)
    if inc["status"] != "OPEN":
        raise ApiError("ERR_INCIDENT_NOT_OPEN", 409, "Incident is not OPEN")
    inc["status"] = "VOID"
    touch(inc)
    _recompute_line(inc)
    return ok(public(inc))
