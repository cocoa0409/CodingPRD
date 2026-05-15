"""Financing application endpoints (PRD §3.5)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, request

from ..auth import require_auth
from ..calculations import (
    compute_approved_apr_bps,
    compute_effective_apr_bps,
    composite_risk_score,
    composite_to_rating,
)
from ..clock import clock
from ..constants import (
    APR_CEILING_BPS,
    APR_FLOOR_BPS,
    FINANCING_MODES,
    FRAUD_RISK_THRESHOLD,
    KYC_VALIDITY_DAYS,
    MAX_REVISION_ROUNDS,
)
from ..errors import api_error
from ..response import list_envelope, success_envelope
from ..store import store
from ..utils import (
    check_version,
    get_json_body,
    optional_int,
    optional_str,
    page_slice,
    parse_iso_or_none,
    parse_pagination,
    require_int,
    require_str,
)

bp = Blueprint("financing_applications", __name__, url_prefix="/scf/financing-applications")

READ_ROLES = ("SupplierUser", "RiskReviewer", "CreditApprover", "Funder", "PlatformAdmin")


def _kyc_within_validity(supplier: dict) -> bool:
    if supplier.get("kyc_status") != "PASSED":
        return False
    completed = parse_iso_or_none(supplier.get("kyc_completed_at"))
    if completed is None:
        return False
    delta = clock.now() - completed
    return delta <= timedelta(days=KYC_VALIDITY_DAYS)


def _find_reviewer_id(app_id: str):
    """Return the X-User-ID of the actor that recorded the start-review audit
    for this application, or None if not found."""
    for log in reversed(store.audit_logs):
        if (
            log.get("entity_type") == "FinancingApplication"
            and log.get("entity_id") == app_id
            and log.get("action") == "REGISTER"
            and log.get("actor_role") == "RiskReviewer"
        ):
            return log.get("actor_id")
    return None


# ---- POST /scf/financing-applications ----
@bp.post("")
@require_auth(["SupplierUser"])
def create_application():
    body = get_json_body()
    receivable_id = require_str(body, "receivable_id")
    mode = require_str(body, "mode")
    if mode not in FINANCING_MODES:
        raise api_error("ERR_VALIDATION", "Invalid financing mode")
    requested_amount = require_int(body, "requested_amount_cents")
    if requested_amount <= 0:
        raise api_error("ERR_AMOUNT_NON_POSITIVE", "requested_amount_cents must be > 0")
    term_days = require_int(body, "term_days")
    if term_days < 1 or term_days > 365:
        raise api_error("ERR_VALIDATION", "term_days must be in [1, 365]")
    doc_ids = body.get("supporting_doc_ids", [])
    if not isinstance(doc_ids, list):
        raise api_error("ERR_VALIDATION", "supporting_doc_ids must be an array")

    receivable = store.receivables.get(receivable_id)
    if receivable is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "receivable_id not found")

    if g.user_id != receivable.get("supplier_id"):
        raise api_error("ERR_OWNERSHIP_VIOLATION", "SupplierUser does not own this receivable")

    supplier = store.suppliers.get(receivable["supplier_id"])
    if supplier and supplier.get("status") == "BLACKLISTED":
        raise api_error("ERR_SUPPLIER_BLACKLISTED", "Supplier is BLACKLISTED")

    with store.lock:
        payload = {
            "receivable_id": receivable_id,
            "supplier_id": receivable["supplier_id"],
            "mode": mode,
            "requested_amount_cents": requested_amount,
            "term_days": term_days,
            "supporting_doc_ids": list(doc_ids),
            "pinned_core_enterprise_version": None,
            "pinned_receivable_version": None,
            "status": "DRAFT",
            "risk_rating": None,
            "approved_amount_cents": None,
            "approved_apr_bps": None,
            "effective_apr_bps": None,
            "revision_round": 0,
        }
        store.stamp_create(payload)
        store.financing_applications[payload["id"]] = payload
    return success_envelope(payload, status=201)


# ---- POST /scf/financing-applications/{id}/submit ----
@bp.post("/<aid>/submit")
@require_auth(["SupplierUser"])
def submit_application(aid):
    app = store.financing_applications.get(aid)
    if app is None:
        raise api_error("ERR_NOT_FOUND", "Application not found")
    if g.user_id != app.get("supplier_id"):
        raise api_error("ERR_OWNERSHIP_VIOLATION", "SupplierUser does not own this application")
    body = get_json_body()
    if app.get("status") not in ("DRAFT", "RETURNED_FOR_REVISION"):
        check_version(body, app)
        raise api_error("ERR_INVALID_STATE", "Application must be DRAFT or RETURNED_FOR_REVISION")
    check_version(body, app)

    supplier = store.suppliers.get(app["supplier_id"])

    receivable = store.receivables.get(app["receivable_id"])
    if receivable is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "Receivable not found")
    if receivable.get("status") not in ("REGISTERED", "PLEDGED"):
        raise api_error("ERR_INVALID_STATE", "Receivable must be REGISTERED or PLEDGED")

    # PRD §2.10 business-safety ladder: KYC validity, then supplier
    # not blacklisted, then anti-double-financing. KYC fires first.
    if not _kyc_within_validity(supplier):
        raise api_error("ERR_KYC_EXPIRED_OR_FAILED", "Supplier KYC is not valid")

    if supplier and supplier.get("status") == "BLACKLISTED":
        raise api_error("ERR_SUPPLIER_BLACKLISTED", "Supplier is BLACKLISTED")

    # Anti double-financing: no other active (non-terminal) application for the same receivable
    for other in store.financing_applications.values():
        if other.get("id") == app["id"]:
            continue
        if other.get("receivable_id") != app["receivable_id"]:
            continue
        if other.get("status") in ("REJECTED", "CANCELLED", "DISBURSED"):
            continue
        raise api_error("ERR_RECEIVABLE_ALREADY_FINANCED", "Active application exists for this receivable")

    # Term match
    due_dt = parse_iso_or_none(receivable.get("due_date"))
    if due_dt is None:
        raise api_error("ERR_VALIDATION", "Receivable has no due_date")
    expected_term = int((due_dt - clock.now()).total_seconds() // 86400)
    diff = abs(int(app["term_days"]) - expected_term)
    if diff > 1:
        raise api_error("ERR_TERM_MISMATCH", "term_days does not match due_date offset")

    # On first submission, compute composite risk rating
    with store.lock:
        if app.get("risk_rating") is None:
            ce = None
            confirmation = store.payable_confirmations.get(receivable.get("confirmation_id"))
            if confirmation:
                ce = store.core_enterprises.get(confirmation.get("core_enterprise_id"))
            score = composite_risk_score(
                mode=app["mode"],
                kyc_status=supplier.get("kyc_status", "NOT_RUN"),
                aml_risk_score=float(supplier.get("aml_risk_score", 0.0)),
                tier_to_core=int(supplier.get("tier_to_core", 1)),
                core_risk_rating=(ce or {}).get("risk_rating", "BBB"),
            )
            app["risk_rating"] = composite_to_rating(score)
            app["composite_score"] = float(score)
        app["status"] = "SUBMITTED"
        store.stamp_update(app)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="FinancingApplication",
            entity_id=app["id"],
            action="REGISTER",
            amount_cents=int(app["requested_amount_cents"]),
        )
    return success_envelope(app)


# ---- POST /scf/financing-applications/{id}/start-review ----
@bp.post("/<aid>/start-review")
@require_auth(["RiskReviewer"])
def start_review(aid):
    app = store.financing_applications.get(aid)
    if app is None:
        raise api_error("ERR_NOT_FOUND", "Application not found")
    body = get_json_body()
    if app.get("status") != "SUBMITTED":
        check_version(body, app)
        raise api_error("ERR_INVALID_STATE", "Application must be SUBMITTED")
    check_version(body, app)

    # Require a passing verification on the receivable
    receivable_id = app.get("receivable_id")
    has_pass = False
    for verif in store.verifications.values():
        if verif.get("receivable_id") == receivable_id and verif.get("outcome") == "PASS":
            has_pass = True
            break
    if not has_pass:
        raise api_error("ERR_INVALID_STATE", "Trade-background verification PASS required")

    with store.lock:
        app["status"] = "UNDER_REVIEW"
        store.stamp_update(app)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="FinancingApplication",
            entity_id=app["id"],
            action="REGISTER",
        )
    return success_envelope(app)


# ---- POST /scf/financing-applications/{id}/return ----
@bp.post("/<aid>/return")
@require_auth(["RiskReviewer"])
def return_application(aid):
    app = store.financing_applications.get(aid)
    if app is None:
        raise api_error("ERR_NOT_FOUND", "Application not found")
    body = get_json_body()
    if app.get("status") != "UNDER_REVIEW":
        check_version(body, app)
        raise api_error("ERR_INVALID_STATE", "Application must be UNDER_REVIEW")
    check_version(body, app)
    revision_notes = require_str(body, "revision_notes")
    if int(app.get("revision_round", 0)) >= MAX_REVISION_ROUNDS:
        raise api_error("ERR_MAX_REVISIONS_EXCEEDED", "Maximum revision rounds exceeded")
    with store.lock:
        app["status"] = "RETURNED_FOR_REVISION"
        app["revision_round"] = int(app.get("revision_round", 0)) + 1
        app["revision_notes"] = revision_notes
        store.stamp_update(app)
    return success_envelope(app)


# ---- POST /scf/financing-applications/{id}/approve ----
@bp.post("/<aid>/approve")
@require_auth(["CreditApprover"])
def approve_application(aid):
    app = store.financing_applications.get(aid)
    if app is None:
        raise api_error("ERR_NOT_FOUND", "Application not found")
    body = get_json_body()

    # Segregation of duties: approver must not equal the reviewer who started review
    reviewer_id = _find_reviewer_id(aid)
    if reviewer_id is not None and reviewer_id == g.user_id:
        raise api_error("ERR_SEGREGATION_OF_DUTIES", "Approver must differ from reviewer")

    if app.get("status") != "UNDER_REVIEW":
        check_version(body, app)
        raise api_error("ERR_INVALID_STATE", "Application must be UNDER_REVIEW")
    check_version(body, app)

    approved_amount = require_int(body, "approved_amount_cents")
    if approved_amount <= 0:
        raise api_error("ERR_AMOUNT_NON_POSITIVE", "approved_amount_cents must be > 0")

    receivable = store.receivables.get(app["receivable_id"])
    if receivable is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "Receivable not found")
    supplier = store.suppliers.get(app["supplier_id"])
    if supplier is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "Supplier not found")
    confirmation = store.payable_confirmations.get(receivable.get("confirmation_id"))
    if confirmation is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "Confirmation not found")
    ce = store.core_enterprises.get(confirmation.get("core_enterprise_id"))
    if ce is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "Core enterprise not found")

    # KYC check
    if not _kyc_within_validity(supplier):
        raise api_error("ERR_KYC_EXPIRED_OR_FAILED", "Supplier KYC invalid")
    # Core enterprise must be APPROVED (not SUSPENDED)
    if ce.get("onboarding_status") != "APPROVED":
        if ce.get("onboarding_status") == "SUSPENDED":
            raise api_error("ERR_CORE_ENTERPRISE_SUSPENDED", "CoreEnterprise is SUSPENDED")
        raise api_error("ERR_CORE_ENTERPRISE_NOT_APPROVED", "CoreEnterprise is not APPROVED")

    # Trade-background verification PASS
    has_pass = any(
        v.get("receivable_id") == receivable["id"] and v.get("outcome") == "PASS"
        for v in store.verifications.values()
    )
    if not has_pass:
        raise api_error("ERR_INVALID_STATE", "Trade-background verification PASS required")

    # Fraud-risk threshold
    if float(supplier.get("aml_risk_score", 0.0)) >= FRAUD_RISK_THRESHOLD:
        raise api_error("ERR_FRAUD_RISK_THRESHOLD", "Supplier AML risk above threshold")

    # Approved amount in [0, requested] and [0, receivable.amount]
    if (
        approved_amount > int(app["requested_amount_cents"])
        or approved_amount > int(receivable.get("amount_cents", 0))
    ):
        raise api_error("ERR_APPROVED_AMOUNT_OUT_OF_RANGE", "approved_amount_cents out of range")

    # Credit-line sufficiency at decision time
    available = (
        int(ce.get("credit_line_total_cents", 0))
        - int(ce.get("credit_line_reserved_cents", 0))
        - int(ce.get("credit_line_consumed_cents", 0))
    )
    if approved_amount > available:
        raise api_error("ERR_CREDIT_LINE_INSUFFICIENT", "Available headroom below approved amount")

    # Risk rating must not be REJECT
    if app.get("risk_rating") == "REJECT":
        raise api_error("ERR_FRAUD_RISK_THRESHOLD", "Risk rating REJECT cannot reach approval")

    # Pricing
    apr_bps = compute_approved_apr_bps(
        mode=app["mode"],
        core_risk_rating=ce.get("risk_rating", "BBB"),
        supplier_app_risk_rating=app.get("risk_rating") or "LOW",
        supplier_tier=int(supplier.get("tier_to_core", 1)),
    )
    if apr_bps < APR_FLOOR_BPS or apr_bps > APR_CEILING_BPS:
        raise api_error("ERR_APR_OUT_OF_RANGE", "Computed APR outside [floor, ceiling]")

    with store.lock:
        app["status"] = "APPROVED"
        app["approved_amount_cents"] = approved_amount
        app["approved_apr_bps"] = apr_bps
        if app["mode"] == "DYNAMIC_DISCOUNTING":
            app["effective_apr_bps"] = compute_effective_apr_bps(apr_bps, int(app["term_days"]))
        else:
            app["effective_apr_bps"] = None
        app["pinned_core_enterprise_version"] = int(ce.get("version", 1))
        app["pinned_receivable_version"] = int(receivable.get("version", 1))
        store.stamp_update(app)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="FinancingApplication",
            entity_id=app["id"],
            action="APPROVE",
            amount_cents=approved_amount,
        )
    return success_envelope(app)


# ---- POST /scf/financing-applications/{id}/reject ----
@bp.post("/<aid>/reject")
@require_auth(["CreditApprover"])
def reject_application(aid):
    app = store.financing_applications.get(aid)
    if app is None:
        raise api_error("ERR_NOT_FOUND", "Application not found")
    body = get_json_body()

    reviewer_id = _find_reviewer_id(aid)
    if reviewer_id is not None and reviewer_id == g.user_id:
        raise api_error("ERR_SEGREGATION_OF_DUTIES", "Approver must differ from reviewer")

    if app.get("status") != "UNDER_REVIEW":
        check_version(body, app)
        raise api_error("ERR_INVALID_STATE", "Application must be UNDER_REVIEW")
    check_version(body, app)
    reject_reason = require_str(body, "reject_reason")
    with store.lock:
        app["status"] = "REJECTED"
        app["reject_reason"] = reject_reason
        store.stamp_update(app)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="FinancingApplication",
            entity_id=app["id"],
            action="REJECT",
        )
    return success_envelope(app)


# ---- GET /scf/financing-applications/{id} ----
@bp.get("/<aid>")
@require_auth(READ_ROLES)
def get_application(aid):
    app = store.financing_applications.get(aid)
    if app is None:
        raise api_error("ERR_NOT_FOUND", "Application not found")
    if g.user_role == "SupplierUser" and g.user_id != app.get("supplier_id"):
        raise api_error("ERR_OWNERSHIP_VIOLATION", "SupplierUser does not own this application")
    return success_envelope(app)


# ---- GET /scf/financing-applications ----
@bp.get("")
@require_auth(READ_ROLES)
def list_applications():
    limit, offset = parse_pagination()
    supplier_id = request.args.get("supplier_id")
    status = request.args.get("status")
    mode = request.args.get("mode")

    items = list(store.financing_applications.values())
    if supplier_id:
        items = [a for a in items if a.get("supplier_id") == supplier_id]
    if status:
        items = [a for a in items if a.get("status") == status]
    if mode:
        items = [a for a in items if a.get("mode") == mode]

    if g.user_role == "SupplierUser":
        items = [a for a in items if a.get("supplier_id") == g.user_id]
    items.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    page, total = page_slice(items, limit, offset)
    return list_envelope(page, total, limit, offset)
