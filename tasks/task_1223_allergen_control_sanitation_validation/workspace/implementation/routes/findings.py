from flask import Blueprint, request

from db import db, new_entity, public, touch
from errors import ApiError
from logic import SEVERITY_POINTS, get_or_404, recompute_training
from middleware import require_roles
from response import ok, ok_list
from util import body, req_dt_str, req_enum, req_str

bp = Blueprint("findings", __name__)

READ_ROLES = ("QaManager", "QaSupervisor", "Auditor")
FINDING_TYPES = ("PROCEDURE_DEVIATION", "DOCUMENTATION_GAP",
                 "TRAINING_DEFICIENCY", "SWAB_TECHNIQUE", "LABEL_CONTROL")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")


@bp.post("/qa/audit-findings")
@require_roles("Auditor")
def create_finding():
    b = body()
    tech = get_or_404("technicians", req_str(b, "technician_id"))
    auditor = get_or_404("technicians", req_str(b, "auditor_id"))
    finding_type = req_enum(b, "finding_type", FINDING_TYPES)
    severity = req_enum(b, "severity", SEVERITIES)
    due = req_dt_str(b, "corrective_action_due_utc")
    if auditor["status"] != "ACTIVE":
        raise ApiError("ERR_TECH_NOT_ACTIVE", 403,
                       "Auditor is not ACTIVE")
    if auditor["id"] == tech["id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "auditor_id must differ from technician_id")
    ent = new_entity({
        "technician_id": tech["id"],
        "auditor_id": auditor["id"],
        "finding_type": finding_type,
        "severity": severity,
        "points_deducted": SEVERITY_POINTS[severity],
        "corrective_action_due_utc": due,
        "corrective_action_note": None,
        "status": "OPEN",
        "_overdue_penalty": False,
    })
    db["findings"][ent["id"]] = ent
    recompute_training(tech)
    return ok(public(ent), 201)


@bp.get("/qa/audit-findings")
@require_roles(*READ_ROLES)
def list_findings():
    items = list(db["findings"].values())
    for param in ("technician_id", "auditor_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [f for f in items if f.get(param) == v]
    return ok_list(items)


@bp.get("/qa/audit-findings/<findingId>")
@require_roles(*READ_ROLES)
def get_finding(findingId):
    return ok(public(get_or_404("findings", findingId)))


@bp.post("/qa/audit-findings/<findingId>/resolve")
@require_roles("QaSupervisor")
def resolve_finding(findingId):
    f = get_or_404("findings", findingId)
    if f["status"] not in ("OPEN", "OVERDUE"):
        raise ApiError("ERR_FINDING_NOT_OPEN", 409,
                       "Finding is not OPEN or OVERDUE")
    b = body()
    note = req_str(b, "corrective_action_note")
    f["corrective_action_note"] = note
    f["status"] = "RESOLVED"
    touch(f)
    tech = db["technicians"].get(f["technician_id"])
    if tech is not None:
        recompute_training(tech)
    return ok(public(f))


@bp.post("/qa/audit-findings/<findingId>/waive")
@require_roles("QaManager")
def waive_finding(findingId):
    f = get_or_404("findings", findingId)
    if f["status"] != "OPEN":
        raise ApiError("ERR_FINDING_NOT_OPEN", 409, "Finding is not OPEN")
    if f["severity"] != "MINOR":
        raise ApiError("ERR_FINDING_NOT_MINOR", 422,
                       "Only MINOR findings may be waived")
    f["status"] = "WAIVED"
    touch(f)
    tech = db["technicians"].get(f["technician_id"])
    if tech is not None:
        recompute_training(tech)
    return ok(public(f))
