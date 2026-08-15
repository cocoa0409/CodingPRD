"""Escalations: acknowledge / manual resolve (PRD §3.9)."""

from flask import Blueprint, request

from db import now_clock, store, touch
from errors import invalid_state
from middleware import auth_context, get_body, get_or_404, req_str, require_roles
from response import paginate, success_object
from serializers import created_sorted, escalation_to_api
from services.audit import append_audit

bp = Blueprint("escalations", __name__)


@bp.get("/compliance/escalations")
def list_escalations():
    auth_context()
    items = created_sorted(store.escalations.values())
    for param in ("status", "target_type", "target_id", "business_owner_id",
                  "trigger_rule"):
        value = request.args.get(param)
        if value is not None:
            items = [e for e in items if e[param] == value]
    return paginate(items, escalation_to_api)


@bp.get("/compliance/escalations/<escalation_id>")
def get_escalation(escalation_id):
    auth_context()
    escalation = get_or_404(store.escalations, escalation_id, "escalation")
    return success_object(escalation_to_api(escalation))


@bp.post("/compliance/escalations/<escalation_id>/acknowledge")
def acknowledge_escalation(escalation_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceManager",))
    escalation = get_or_404(store.escalations, escalation_id, "escalation")
    if escalation["status"] != "OPEN":
        raise invalid_state("acknowledge requires status OPEN")
    escalation["status"] = "ACKNOWLEDGED"
    touch(escalation)
    append_audit(user_id, role, "POST /compliance/escalations/{id}/acknowledge",
                 "Escalation", escalation["id"])
    return success_object(escalation_to_api(escalation))


@bp.post("/compliance/escalations/<escalation_id>/resolve")
def resolve_escalation(escalation_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceManager",))
    body = get_body()
    req_str(body, "resolution_note")
    escalation = get_or_404(store.escalations, escalation_id, "escalation")
    if escalation["status"] not in ("OPEN", "ACKNOWLEDGED"):
        raise invalid_state("resolve requires status OPEN or ACKNOWLEDGED")
    escalation["status"] = "RESOLVED"
    escalation["resolution_code"] = "MANUAL_RESOLUTION"
    escalation["resolved_at"] = now_clock()
    touch(escalation)
    append_audit(user_id, role, "POST /compliance/escalations/{id}/resolve",
                 "Escalation", escalation["id"])
    return success_object(escalation_to_api(escalation))
