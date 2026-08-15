"""Routes: audit results, disputes, billing transactions, mod revisions."""
from datetime import timedelta

import db
import services
from db import policies, work_orders, results, disputes, billings, mod_revisions
from errors import raise_err
from middleware import (
    Ctx, authenticate, require_role, get_body, check_allowed,
    req_enum, req_int, parse_pagination,
)
from response import ok, created, ok_list

from flask import Blueprint

bp = Blueprint("results", __name__)

GROUNDS = {
    "CLASSIFICATION_ERROR", "PAYROLL_ERROR", "SUBCONTRACTOR_INCLUSION",
    "CERT_REVIEW_ERROR", "OTHER",
}


def _insured_scope_for_wo(wo):
    if Ctx.role == "Insured" and wo and wo["policy_id"] != Ctx.user_id:
        raise_err("ERR_FORBIDDEN_SCOPE",
                  "Insured may only access own policy graph")


def _load_result(result_id):
    r = results.get(result_id)
    if r is None:
        raise_err("ERR_AUDIT_RESULT_NOT_FOUND", "AuditResult id does not exist")
    return r


def _load_dispute(dispute_id):
    d = disputes.get(dispute_id)
    if d is None:
        raise_err("ERR_DISPUTE_NOT_FOUND", "Dispute id does not exist")
    return d


def _load_billing(billing_id):
    b = billings.get(billing_id)
    if b is None:
        raise_err("ERR_BILLING_NOT_FOUND", "BillingTransaction id does not exist")
    return b


# --- audit results ------------------------------------------------------------------

@bp.route("/audit-results/<result_id>", methods=["GET"])
def get_result(result_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager", "Underwriter",
                 "BillingClerk")
    r = _load_result(result_id)
    wo = work_orders.get(r["audit_work_order_id"])
    _insured_scope_for_wo(wo)
    return ok(db.serialize(r))


@bp.route("/audit-results/<result_id>/disputes", methods=["POST"])
def create_dispute(result_id):
    authenticate()
    body = get_body()
    check_allowed(body, {"grounds"})
    grounds = req_enum(body, "grounds", GROUNDS)
    require_role("Insured")
    r = _load_result(result_id)
    wo = work_orders.get(r["audit_work_order_id"])
    _insured_scope_for_wo(wo)
    if r["status"] != "ISSUED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only ISSUED results can be disputed")
    deadline = db.parse_dt(r["issued_at"]) + \
        timedelta(days=services.DISPUTE_WINDOW_DAYS)
    if not db.clock_now() <= deadline:
        raise_err("ERR_DISPUTE_WINDOW_CLOSED",
                  "Dispute filed after issued_at + 30 days")
    ent = db.new_entity({
        "audit_result_id": r["id"],
        "grounds": grounds,
        "filed_at": db.now_iso(),
        "status": "FILED",
        "reviewed_by_user_id": None,
    })
    disputes[ent["id"]] = ent
    r["status"] = "DISPUTED"
    db.touch(r)
    if wo is not None:
        wo["status"] = "DISPUTED"
        db.touch(wo)
    return created(db.serialize(ent))


@bp.route("/audit-results/<result_id>/disputes", methods=["GET"])
def list_disputes_of_result(result_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager", "Underwriter")
    r = _load_result(result_id)
    wo = work_orders.get(r["audit_work_order_id"])
    _insured_scope_for_wo(wo)
    limit, offset = parse_pagination()
    items = [d for d in disputes.values() if d["audit_result_id"] == r["id"]]
    items = [db.serialize(d) for d in db.by_created(items)]
    return ok_list(items, limit, offset)


@bp.route("/audit-results/<result_id>/billing-transactions", methods=["GET"])
def list_billings_of_result(result_id):
    authenticate()
    require_role("Insured", "AuditManager", "Underwriter", "BillingClerk")
    r = _load_result(result_id)
    wo = work_orders.get(r["audit_work_order_id"])
    _insured_scope_for_wo(wo)
    limit, offset = parse_pagination()
    items = services.billings_of_result(r["id"])
    items = [db.serialize(b) for b in db.by_created(items)]
    return ok_list(items, limit, offset)


# --- disputes --------------------------------------------------------------------------

@bp.route("/disputes/<dispute_id>", methods=["GET"])
def get_dispute(dispute_id):
    authenticate()
    require_role("Insured", "AuditManager", "Underwriter")
    d = _load_dispute(dispute_id)
    r = results.get(d["audit_result_id"])
    wo = work_orders.get(r["audit_work_order_id"]) if r else None
    _insured_scope_for_wo(wo)
    return ok(db.serialize(d))


def _sod_check_against_issuer(result):
    if result and result.get("issued_by_user_id") is not None and \
            Ctx.user_id == result["issued_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "Reviewer must differ from the result issuer")


@bp.route("/disputes/<dispute_id>/start-review", methods=["POST"])
def start_review(dispute_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("AuditManager")
    d = _load_dispute(dispute_id)
    r = results.get(d["audit_result_id"])
    _sod_check_against_issuer(r)
    if d["status"] != "FILED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only FILED disputes can move to UNDER_REVIEW")
    d["status"] = "UNDER_REVIEW"
    d["reviewed_by_user_id"] = Ctx.user_id
    db.touch(d)
    return ok(db.serialize(d))


@bp.route("/disputes/<dispute_id>/uphold", methods=["POST"])
def uphold_dispute(dispute_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("AuditManager")
    d = _load_dispute(dispute_id)
    r = results.get(d["audit_result_id"])
    _sod_check_against_issuer(r)
    if d["status"] != "UNDER_REVIEW":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only UNDER_REVIEW disputes can be upheld")
    d["status"] = "UPHELD"
    db.touch(d)
    r["status"] = "SUPERSEDED"
    db.touch(r)
    for b in services.billings_of_result(r["id"]):
        if b["status"] in ("ISSUED", "PAST_DUE"):
            b["status"] = "CANCELLED"
            db.touch(b)
    wo = work_orders.get(r["audit_work_order_id"])
    policy = policies.get(wo["policy_id"]) if wo else None
    new_wo = None
    if wo is not None:
        wo["status"] = "SUPERSEDED_BY_REAUDIT"
        db.touch(wo)
        new_wo = db.new_entity({
            "policy_id": wo["policy_id"],
            "selection_run_id": None,
            "reaudit_of_work_order_id": wo["id"],
            "assigned_auditor_id": None,
            "audit_type": "REAUDIT",
            "audit_period_start": policy["effective_date"] if policy else wo["audit_period_start"],
            "audit_period_end": policy["expiration_date"] if policy else wo["audit_period_end"],
            "status": "SELECTED",
            "no_show_count": 0,
            "marked_noncompliant_by_user_id": None,
            "total_premium_base_dollars": 0,
        })
        work_orders[new_wo["id"]] = new_wo
    return ok(db.serialize(d))


@bp.route("/disputes/<dispute_id>/overrule", methods=["POST"])
def overrule_dispute(dispute_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("AuditManager")
    d = _load_dispute(dispute_id)
    r = results.get(d["audit_result_id"])
    _sod_check_against_issuer(r)
    if d["status"] != "UNDER_REVIEW":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only UNDER_REVIEW disputes can be overruled")
    d["status"] = "OVERRULED"
    db.touch(d)
    r["status"] = "ISSUED"
    db.touch(r)
    wo = work_orders.get(r["audit_work_order_id"])
    if wo is not None:
        wo["status"] = "ESTIMATED_BILLED" \
            if r["variant"] == "ESTIMATED_NONCOMPLIANCE" else "BILLED"
        db.touch(wo)
    return ok(db.serialize(d))


# --- billing ----------------------------------------------------------------------------

@bp.route("/billing-transactions/<billing_id>", methods=["GET"])
def get_billing(billing_id):
    authenticate()
    require_role("Insured", "AuditManager", "Underwriter", "BillingClerk")
    b = _load_billing(billing_id)
    r = results.get(b["audit_result_id"])
    wo = work_orders.get(r["audit_work_order_id"]) if r else None
    _insured_scope_for_wo(wo)
    return ok(db.serialize(b))


@bp.route("/billing-transactions/<billing_id>/record-payment", methods=["POST"])
def record_payment(billing_id):
    authenticate()
    body = get_body()
    check_allowed(body, {"amount_cents"})
    amount = req_int(body, "amount_cents", min_value=0)
    require_role("BillingClerk")
    b = _load_billing(billing_id)
    if b["status"] not in ("ISSUED", "PAST_DUE"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Payments can only be recorded against ISSUED or PAST_DUE "
                  "transactions")
    remaining = b["amount_cents"] - b["paid_cents"]
    if amount > remaining:
        raise_err("ERR_OVERPAYMENT",
                  "Payment exceeds remaining balance of the transaction")
    b["paid_cents"] += amount
    if b["paid_cents"] == b["amount_cents"]:
        b["status"] = "PAID" if b["type"] == "ADDITIONAL_PREMIUM_INVOICE" \
            else "APPLIED"
    db.touch(b)
    return ok(db.serialize(b))


# --- mod revisions ------------------------------------------------------------------------

@bp.route("/mod-revisions/<rev_id>/apply", methods=["POST"])
def apply_mod_revision(rev_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("Underwriter")
    rev = mod_revisions.get(rev_id)
    if rev is None:
        raise_err("ERR_MOD_REVISION_NOT_FOUND", "ModRevision id does not exist")
    if rev["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only DRAFT mod revisions can be applied")
    policy = policies.get(rev["policy_id"])
    if policy is not None and policy["status"] == "CANCELLED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Cannot apply a mod revision to a CANCELLED policy")
    rev["status"] = "APPLIED"
    db.touch(rev)
    if policy is not None:
        policy["experience_mod_factor"] = rev["revised_mod_factor"]
        db.touch(policy)
    return ok(db.serialize(rev))
