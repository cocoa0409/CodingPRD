"""Violation remediation and escalation routes."""
from flask import Blueprint, request
from store import store, touch
from auth import require_role, body
from errors import err
from lookups import get_violation, sorted_by_creation
from pagination import paginate
from envelope import success, list_response
from serializers import violation_dict
from domain import escalation_index, create_notice
from calc import ESCALATION_CRITICAL_COUNT

bp = Blueprint("violations", __name__)


@bp.get("/violations/<vid>")
def get_violation_route(vid):
    require_role({"Registrar", "Landlord", "Inspector"})
    v = get_violation(vid)
    return success(violation_dict(v), status=200)


@bp.get("/violations")
def list_violations():
    require_role({"Registrar", "Landlord", "Inspector"})
    items = list(store.violations.values())
    for key in ("property_id", "inspection_id", "checklist_item_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [v for v in items if v.get(key) == val]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return list_response([violation_dict(v) for v in page], limit, offset, total)


@bp.post("/violations/<vid>/submit-remediation")
def submit_remediation(vid):
    uid, role = require_role({"Landlord"})
    v = get_violation(vid)
    prop = store.properties[v["property_id"]]
    if uid != prop["landlord_id"]:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Only the owning landlord may submit remediation")
    if v["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Violation is not OPEN")
    data = body()
    if data.get("remediation_notes") is not None:
        v["remediation_notes"] = data["remediation_notes"]
    v["status"] = "REMEDIATION_SUBMITTED"
    touch(v)
    return success(violation_dict(v), status=200)


@bp.post("/violations/<vid>/escalate")
def escalate_violation(vid):
    require_role({"Registrar"})
    v = get_violation(vid)
    if v["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Violation is not OPEN")
    if v["severity"] != "CRITICAL" or escalation_index(v["property_id"]) < ESCALATION_CRITICAL_COUNT:
        raise err("ERR_ESCALATION_THRESHOLD_NOT_MET", "Escalation threshold not met")
    v["status"] = "ESCALATED"
    touch(v)
    create_notice(v["property_id"], "VIOLATION_NOTICE")
    return success(violation_dict(v), status=200)
