"""Executive / legal escalation path (PRD §3.9)."""
from flask import g, Blueprint

import services as svc
from db import store
from errors import ApiError, ERR_INVALID_STATE_TRANSITION
from middleware import get_body, pagination_params, req_enum, req_str, require_roles
from response import ok, ok_list

bp = Blueprint("escalations", __name__)

RAISERS = ("CaseHandler", "ComplaintManager")
ESC_READERS = ("ComplaintManager", "CaseHandler", "QAReviewer", "ExecutiveReviewer", "Auditor")
ESC_GET_READERS = ("ComplaintManager", "CaseHandler", "ExecutiveReviewer", "Auditor")
EXEC = ("ExecutiveReviewer",)
TIERS = ("EXECUTIVE", "LEGAL")


@bp.post("/complaints/<cid>/escalations")
@require_roles(*RAISERS)
def create_escalation(cid):
    complaint = svc.get_complaint(cid)
    body = get_body()
    tier = req_enum(body, "escalation_tier", TIERS)
    reason = req_str(body, "reason")
    e = svc.fresh_rec(
        complaint_id=complaint.id,
        escalation_tier=tier,
        reason=reason,
        raised_by_user_id=g.user_id,
        status="RAISED",
    )
    store.escalations[e.id] = e
    svc.append_event(complaint.id, "ESCALATED", {"escalation_id": e.id, "escalation_tier": tier})
    return ok(svc.ser_escalation(e), 201)


@bp.get("/complaints/<cid>/escalations")
@require_roles(*ESC_READERS)
def list_escalations(cid):
    svc.get_complaint(cid)
    limit, offset = pagination_params()
    recs = [e for e in store.escalations.values() if e.complaint_id == cid]
    items, total = svc.paged(recs, svc.ser_escalation, limit, offset)
    return ok_list(items, total, limit, offset)


@bp.get("/escalations/<escalationId>")
@require_roles(*ESC_GET_READERS)
def get_escalation(escalationId):
    return ok(svc.ser_escalation(svc.get_escalation(escalationId)), 200)


@bp.post("/escalations/<escalationId>/acknowledge")
@require_roles(*EXEC)
def acknowledge(escalationId):
    e = svc.get_escalation(escalationId)
    if e.status != "RAISED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Escalation status is {e.status}; acknowledge requires RAISED.", 409)
    e.status = "ACKNOWLEDGED"
    svc.touch(e)
    return ok(svc.ser_escalation(e), 200)


@bp.post("/escalations/<escalationId>/resolve")
@require_roles(*EXEC)
def resolve_escalation(escalationId):
    e = svc.get_escalation(escalationId)
    if e.status != "ACKNOWLEDGED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Escalation status is {e.status}; resolve requires ACKNOWLEDGED.", 409)
    e.status = "RESOLVED"
    svc.touch(e)
    svc.append_event(e.complaint_id, "ESCALATION_RESOLVED", {"escalation_id": e.id})
    return ok(svc.ser_escalation(e), 200)


@bp.post("/escalations/<escalationId>/dismiss")
@require_roles(*EXEC)
def dismiss(escalationId):
    e = svc.get_escalation(escalationId)
    if e.status != "RAISED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Escalation status is {e.status}; dismiss requires RAISED.", 409)
    e.status = "DISMISSED"
    svc.touch(e)
    return ok(svc.ser_escalation(e), 200)
