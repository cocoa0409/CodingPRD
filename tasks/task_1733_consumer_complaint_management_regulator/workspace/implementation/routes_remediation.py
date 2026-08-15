"""Remediation and restitution decisions (PRD §3.6)."""
from flask import g, request, Blueprint

import services as svc
from db import store
from errors import (
    ApiError,
    ERR_COMPLAINT_NOT_REMEDIABLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_RESTITUTION_OVER_AUTHORITY,
    ERR_SOD_SELF_APPROVAL,
    ERR_STALE_VERSION,
)
from middleware import get_body, pagination_params, req_enum, req_int, require_roles
from response import ok, ok_list

bp = Blueprint("remediation", __name__)

DECISION_TYPES = ("NO_ACTION", "CORRECTION", "RESTITUTION", "CORRECTION_AND_RESTITUTION")
DECISION_READERS = ("ComplaintManager", "CaseHandler", "QAReviewer", "RemediationApprover", "ExecutiveReviewer", "Auditor")
REMEDIABLE_STATUSES = ("INVESTIGATING", "RESPONSE_DRAFTED", "RESPONSE_QA", "RESOLVED", "REOPENED")


def _validate_line_items(body):
    if "line_items" not in body or not isinstance(body["line_items"], list):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'line_items' is required and must be an array.", 400)
    for li in body["line_items"]:
        if not isinstance(li, dict):
            raise ApiError(ERR_INVALID_REQUEST, "Each line item must be an object.", 400)
        if "label" not in li or not isinstance(li["label"], str):
            raise ApiError(ERR_INVALID_REQUEST, "Each line item requires a string 'label'.", 400)
        if "amount_cents" not in li or not isinstance(li["amount_cents"], int) or isinstance(li["amount_cents"], bool):
            raise ApiError(ERR_INVALID_REQUEST, "Each line item requires an integer 'amount_cents'.", 400)
        if li["amount_cents"] < 0:
            raise ApiError(ERR_INVALID_REQUEST, "Line item amount_cents must be >= 0.", 400)
        if "rounding_rate_bps" in li and li["rounding_rate_bps"] is not None:
            rate = li["rounding_rate_bps"]
            if not isinstance(rate, int) or isinstance(rate, bool) or rate < 0:
                raise ApiError(ERR_INVALID_REQUEST, "Line item rounding_rate_bps must be an integer >= 0.", 400)
    return body["line_items"]


@bp.post("/complaints/<cid>/remediation_decisions")
@require_roles("CaseHandler")
def create_decision(cid):
    complaint = svc.get_complaint(cid)
    body = get_body()
    decision_type = req_enum(body, "decision_type", DECISION_TYPES)
    line_items = _validate_line_items(body)
    expected = req_int(body, "expected_complaint_version")
    # OCC staleness is always the last gate (PRD §2.6).
    if expected != complaint.version:
        raise ApiError(ERR_STALE_VERSION, "expected_complaint_version does not match the complaint's current version.", 412)
    d = svc.fresh_rec(
        complaint_id=complaint.id,
        decision_type=decision_type,
        line_items=line_items,
        restitution_amount_cents=svc.compute_restitution_amount(line_items),
        drafted_by_user_id=g.user_id,
        approved_by_user_id=None,
        status="DRAFT",
    )
    store.decisions[d.id] = d
    # Drafting advances the complaint's basis: bump the parent version.
    svc.touch(complaint)
    return ok(svc.ser_decision(d), 201)


@bp.get("/complaints/<cid>/remediation_decisions")
@require_roles(*DECISION_READERS)
def list_decisions(cid):
    svc.get_complaint(cid)
    limit, offset = pagination_params()
    recs = [d for d in store.decisions.values() if d.complaint_id == cid]
    status = request.args.get("status")
    if status is not None:
        recs = [d for d in recs if d.status == status]
    items, total = svc.paged(recs, svc.ser_decision, limit, offset)
    return ok_list(items, total, limit, offset)


@bp.get("/remediation-decisions/<decisionId>")
@require_roles(*DECISION_READERS)
def get_decision(decisionId):
    return ok(svc.ser_decision(svc.get_decision(decisionId)), 200)


@bp.post("/remediation-decisions/<decisionId>/submit")
@require_roles("CaseHandler")
def submit_decision(decisionId):
    d = svc.get_decision(decisionId)
    if d.status != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Decision status is {d.status}; submit requires DRAFT.", 409)
    if d.decision_type in ("RESTITUTION", "CORRECTION_AND_RESTITUTION"):
        if not d.line_items or d.restitution_amount_cents <= 0:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "A RESTITUTION decision requires non-empty line_items and restitution_amount_cents > 0.",
                400,
            )
    complaint = svc.get_complaint(d.complaint_id)
    if complaint.status not in REMEDIABLE_STATUSES:
        raise ApiError(
            ERR_COMPLAINT_NOT_REMEDIABLE,
            f"Complaint status is {complaint.status}; remediation requires one of {list(REMEDIABLE_STATUSES)}.",
            409,
        )
    d.status = "PENDING_APPROVAL"
    svc.touch(d)
    return ok(svc.ser_decision(d), 200)


@bp.post("/remediation-decisions/<decisionId>/approve")
@require_roles("RemediationApprover")
def approve_decision(decisionId):
    d = svc.get_decision(decisionId)
    # Segregation of duties (7) surfaces before the state check (8).
    if g.user_id == d.drafted_by_user_id:
        raise ApiError(ERR_SOD_SELF_APPROVAL, "An approver may not approve a decision they drafted.", 409)
    if d.status != "PENDING_APPROVAL":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Decision status is {d.status}; approve requires PENDING_APPROVAL.", 409)
    # Authority cap (16).
    if d.restitution_amount_cents > svc.RESTITUTION_AUTHORITY_CAP_CENTS:
        header = request.headers.get("X-Manager-Authority")
        if header is None or header.lower() != "true":
            raise ApiError(
                ERR_RESTITUTION_OVER_AUTHORITY,
                "Approving restitution above the authority cap requires X-Manager-Authority: true.",
                409,
            )
    d.status = "APPROVED"
    d.approved_by_user_id = g.user_id
    svc.touch(d)
    complaint = svc.get_complaint(d.complaint_id)
    svc.recompute_restitution(complaint)
    svc.append_event(complaint.id, "REMEDIATION_APPROVED", {"decision_id": d.id, "restitution_amount_cents": d.restitution_amount_cents})
    return ok(svc.ser_decision(d), 200)


@bp.post("/remediation-decisions/<decisionId>/reject")
@require_roles("RemediationApprover")
def reject_decision(decisionId):
    d = svc.get_decision(decisionId)
    if g.user_id == d.drafted_by_user_id:
        raise ApiError(ERR_SOD_SELF_APPROVAL, "An approver may not reject a decision they drafted.", 409)
    if d.status != "PENDING_APPROVAL":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Decision status is {d.status}; reject requires PENDING_APPROVAL.", 409)
    d.status = "REJECTED"
    svc.touch(d)
    return ok(svc.ser_decision(d), 200)


@bp.post("/remediation-decisions/<decisionId>/mark_paid")
@require_roles("CaseHandler")
def mark_paid(decisionId):
    d = svc.get_decision(decisionId)
    if d.status != "APPROVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Decision status is {d.status}; mark_paid requires APPROVED.", 409)
    d.status = "PAID"
    svc.touch(d)
    complaint = svc.get_complaint(d.complaint_id)
    svc.recompute_restitution(complaint)
    svc.append_event(complaint.id, "REMEDIATION_PAID", {"decision_id": d.id, "restitution_amount_cents": d.restitution_amount_cents})
    return ok(svc.ser_decision(d), 200)


@bp.post("/remediation-decisions/<decisionId>/reverse")
@require_roles("RemediationApprover")
def reverse_decision(decisionId):
    d = svc.get_decision(decisionId)
    if d.status != "APPROVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Decision status is {d.status}; reverse requires APPROVED.", 409)
    d.status = "REVERSED"
    svc.touch(d)
    complaint = svc.get_complaint(d.complaint_id)
    svc.recompute_restitution(complaint)
    svc.append_event(complaint.id, "REMEDIATION_REVERSED", {"decision_id": d.id, "restitution_amount_cents": d.restitution_amount_cents})
    return ok(svc.ser_decision(d), 200)
