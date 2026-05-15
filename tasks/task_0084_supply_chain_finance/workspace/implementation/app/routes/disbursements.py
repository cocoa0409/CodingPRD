"""Disbursement endpoints (PRD §3.6)."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..calculations import variant_a_dynamic_discount_cents, variant_a_total_due
from ..clock import clock
from ..errors import api_error
from ..response import success_envelope
from ..store import fmt_ts, store
from ..utils import (
    get_json_body,
    parse_iso_or_none,
    require_str,
)

bp = Blueprint("disbursements", __name__, url_prefix="/scf/disbursements")


# ---- POST /scf/disbursements ----
@bp.post("")
@require_auth(["Funder"])
def release_disbursement():
    body = get_json_body()
    application_id = require_str(body, "application_id")
    funder_account_id = require_str(body, "funder_account_id")

    app = store.financing_applications.get(application_id)
    if app is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "application_id not found")

    if app.get("status") != "APPROVED":
        raise api_error("ERR_INVALID_STATE", "Application must be APPROVED")

    # At most one disbursement per application
    for d in store.disbursements.values():
        if d.get("application_id") == application_id:
            raise api_error("ERR_INVALID_STATE", "Disbursement already exists for this application")

    receivable = store.receivables.get(app["receivable_id"])
    if receivable is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "Receivable not found")
    confirmation = store.payable_confirmations.get(receivable.get("confirmation_id"))
    if confirmation is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "Confirmation not found")
    ce = store.core_enterprises.get(confirmation.get("core_enterprise_id"))
    if ce is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "Core enterprise not found")

    # Core enterprise must not be SUSPENDED at release time
    if ce.get("onboarding_status") == "SUSPENDED":
        raise api_error("ERR_CORE_ENTERPRISE_SUSPENDED", "CoreEnterprise is SUSPENDED")
    if ce.get("onboarding_status") != "APPROVED":
        raise api_error("ERR_CORE_ENTERPRISE_NOT_APPROVED", "CoreEnterprise is not APPROVED")

    # Pin checks
    if int(ce.get("version", 0)) != int(app.get("pinned_core_enterprise_version") or 0):
        raise api_error("ERR_PIN_STALE", "CoreEnterprise version moved since approval")
    if int(receivable.get("version", 0)) != int(app.get("pinned_receivable_version") or 0):
        raise api_error("ERR_PIN_STALE", "Receivable version moved since approval")

    principal = int(app["approved_amount_cents"])
    apr_bps = int(app["approved_apr_bps"])

    now = clock.now()
    due_dt = parse_iso_or_none(receivable.get("due_date"))
    term_days_eff = max(0, int((due_dt - now).total_seconds() // 86400))

    # Variant A: forward-looking total due
    interest, fees, total_due = variant_a_total_due(principal, apr_bps, term_days_eff)

    # Discount for DYNAMIC_DISCOUNTING
    if app.get("mode") == "DYNAMIC_DISCOUNTING":
        discount = variant_a_dynamic_discount_cents(principal, int(app.get("effective_apr_bps") or 0))
    else:
        discount = 0
    net_to_supplier = principal - discount - fees

    with store.lock:
        disbursement = {
            "application_id": application_id,
            "funder_account_id": funder_account_id,
            "principal_cents": principal,
            "discount_cents": discount,
            "net_to_supplier_cents": net_to_supplier,
            "fees_cents": fees,
            "released_at": fmt_ts(now),
            "reconciled_at": None,
        }
        store.stamp_event(disbursement)
        store.disbursements[disbursement["id"]] = disbursement

        # Update application
        app["status"] = "DISBURSED"
        store.stamp_update(app)

        # Update receivable -> FINANCED
        receivable["status"] = "FINANCED"
        store.stamp_update(receivable)

        # Credit-line bookkeeping: reserved -> consumed
        ce["credit_line_reserved_cents"] = max(
            0, int(ce.get("credit_line_reserved_cents", 0)) - principal
        )
        ce["credit_line_consumed_cents"] = int(ce.get("credit_line_consumed_cents", 0)) + principal
        store.stamp_update(ce)

        # Create RepaymentSchedule
        schedule = {
            "application_id": application_id,
            "scheduled_repayment_date": receivable.get("due_date"),
            "total_due_cents": total_due,
            "interest_cents": interest,
            "fees_cents": fees,
            "principal_cents": principal,
            "paid_cents": 0,
            "status": "SCHEDULED",
            "prepayment_count": 0,
            "rebate_cents": 0,
            "prepayments": [],  # list of (timestamp_str, amount)
        }
        store.stamp_create(schedule)
        store.repayment_schedules[schedule["id"]] = schedule

        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="FinancingApplication",
            entity_id=application_id,
            action="DISBURSE",
            amount_cents=principal,
        )
        # PRD §3.10: "Every significant state change appends an
        # AuditLogEntry whose entity_type names the affected entity
        # type" — the entity_type enum explicitly includes
        # RepaymentSchedule. Schedule creation is a significant state
        # change, so emit a REGISTER audit entry for it.
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="RepaymentSchedule",
            entity_id=schedule["id"],
            action="REGISTER",
            amount_cents=total_due,
        )

    return success_envelope(disbursement, status=201)


# ---- POST /scf/disbursements/{id}/reconcile ----
@bp.post("/<did>/reconcile")
@require_auth(["Funder"])
def reconcile_disbursement(did):
    d = store.disbursements.get(did)
    if d is None:
        raise api_error("ERR_NOT_FOUND", "Disbursement not found")
    if d.get("reconciled_at"):
        raise api_error("ERR_INVALID_STATE", "Disbursement already reconciled")
    with store.lock:
        d["reconciled_at"] = fmt_ts(clock.now())
    return success_envelope(d)


# ---- GET /scf/disbursements/{id} ----
@bp.get("/<did>")
@require_auth(["Funder", "CreditApprover", "PlatformAdmin"])
def get_disbursement(did):
    d = store.disbursements.get(did)
    if d is None:
        raise api_error("ERR_NOT_FOUND", "Disbursement not found")
    return success_envelope(d)
