"""AuditSample endpoints (PRD §3.8)."""

from flask import Blueprint, request

import db
import services.domain as domain
from errors import ApiError
from middleware import bump, require_role
from response import created, ok

bp = Blueprint("audit_samples", __name__)

AU = "Auditor"
READ_ROLES = ("TenantAdmin", "ComplianceOfficer", "Auditor")


def _load(tid, sid):
    tenant = domain.get_tenant(tid)
    sample = domain.get_scoped("audit_samples", sid, tenant["id"])
    return tenant, sample


def _after_terminal_outcome(tenant, sample):
    cust = db.stores["customers"].get(sample["customer_id"])
    if cust:
        domain.recompute_audit_standing(cust)
        bump(cust)
    campaign = db.stores["audit_campaigns"].get(sample["campaign_id"])
    if campaign:
        domain.maybe_campaign_to_remediation(campaign, tenant)


@bp.route("/tenants/<tid>/audit_samples/<sid>", methods=["GET"])
def get_sample(tid, sid):
    require_role(*READ_ROLES)
    _, sample = _load(tid, sid)
    return ok(db.pub(sample))


@bp.route("/tenants/<tid>/audit_samples/<sid>/request_docs", methods=["POST"])
def request_docs(tid, sid):
    require_role(AU)
    tenant, sample = _load(tid, sid)
    if sample["outcome"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a PENDING sample can move to DOC_REQUESTED", 409)
    sample["outcome"] = "DOC_REQUESTED"
    sample["doc_due_day_index"] = tenant["audit_clock_day_index"] + domain.DOC_RESPONSE_WINDOW_DAYS
    bump(sample)
    return ok(db.pub(sample))


@bp.route("/tenants/<tid>/audit_samples/<sid>/receive_docs", methods=["POST"])
def receive_docs(tid, sid):
    require_role("ComplianceOfficer")
    tenant, sample = _load(tid, sid)
    if sample["outcome"] != "DOC_REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DOC_REQUESTED sample can receive documents", 409)
    # Priority 24: receipt only on or before doc_due_day_index.
    if tenant["audit_clock_day_index"] > sample["doc_due_day_index"]:
        raise ApiError("ERR_DOC_WINDOW_EXPIRED", "The documentation response window has expired", 409)
    sample["outcome"] = "DOC_RECEIVED"
    bump(sample)
    return ok(db.pub(sample))


@bp.route("/tenants/<tid>/audit_samples/<sid>/request_rework", methods=["POST"])
def request_rework(tid, sid):
    require_role(AU)
    tenant, sample = _load(tid, sid)
    if sample["outcome"] != "DOC_RECEIVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DOC_RECEIVED sample can be returned for rework", 409)
    sample["outcome"] = "DOC_REQUESTED"
    sample["doc_due_day_index"] = tenant["audit_clock_day_index"] + domain.DOC_RESPONSE_WINDOW_DAYS
    bump(sample)
    return ok(db.pub(sample))


@bp.route("/tenants/<tid>/audit_samples/<sid>/pass", methods=["POST"])
def pass_sample(tid, sid):
    require_role(AU)
    tenant, sample = _load(tid, sid)
    if sample["outcome"] != "DOC_RECEIVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DOC_RECEIVED sample can be passed", 409)
    sample["outcome"] = "PASSED"
    bump(sample)
    _after_terminal_outcome(tenant, sample)
    return ok(db.pub(sample))


@bp.route("/tenants/<tid>/audit_samples/<sid>/fail", methods=["POST"])
def fail_sample(tid, sid):
    require_role(AU)
    tenant, sample = _load(tid, sid)
    if sample["outcome"] != "DOC_RECEIVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DOC_RECEIVED sample can be failed", 409)
    body = request.get_json(silent=True) or {}
    sample["outcome"] = "FAILED"
    sample["failure_reason"] = body.get("failure_reason")
    bump(sample)
    # Failing auto-creates a COLLECT_NEW_CERT remediation in OPEN status.
    action = db.make_record({
        "tenant_id": tenant["id"],
        "sample_id": sample["id"],
        "customer_id": sample["customer_id"],
        "action_type": "COLLECT_NEW_CERT",
        "assigned_to_user_id": "system",
        "resolved_by_user_id": None,
        "assessment_amount_cents": None,
        "status": "OPEN",
    })
    db.stores["remediation_actions"][action["id"]] = action
    _after_terminal_outcome(tenant, sample)
    return ok(db.pub(sample))


@bp.route("/tenants/<tid>/audit_samples/<sid>/waive", methods=["POST"])
def waive_sample(tid, sid):
    require_role(AU)
    tenant, sample = _load(tid, sid)
    if sample["outcome"] not in ("DOC_REQUESTED", "DOC_RECEIVED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DOC_REQUESTED or DOC_RECEIVED sample can be waived", 409)
    sample["outcome"] = "WAIVED"
    bump(sample)
    _after_terminal_outcome(tenant, sample)
    return ok(db.pub(sample))
