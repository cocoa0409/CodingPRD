"""Remediation payments."""
from flask import Blueprint, g, request

import db
from errors import already_terminal, err, invalid_state
from middleware import (
    body, check_int, get_or_404, list_page, require_field, require_roles,
)
from response import success_list, success_obj
from services.cap import cap_rollup

bp = Blueprint("remediation_payments", __name__)

ROLES = (
    "FairLendingAnalyst", "FairLendingOfficer", "ComplianceDirector",
    "RemediationSpecialist",
)


@bp.post("/fair-lending/remediation-payments")
@require_roles("RemediationSpecialist")
def create_payment():
    data = body()
    cap_id = require_field(data, "corrective_action_plan_id")
    application_id = require_field(data, "application_id")
    amount_cents = check_int(require_field(data, "amount_cents"), "amount_cents")
    cap = get_or_404("caps", cap_id, "CorrectiveActionPlan")
    get_or_404("applications", application_id, "Application")
    if cap["status"] not in ("EXECUTING", "OVERDUE"):
        raise err(
            "ERR_CAP_NOT_EXECUTING",
            "Manual payments require a CAP in EXECUTING or OVERDUE",
        )
    finding = db.STORES["findings"].get(cap["finding_id"])
    harmed = finding["harmed_application_ids"] if finding is not None else []
    if application_id not in harmed:
        raise err(
            "ERR_PAYEE_NOT_IN_CAP_SCOPE",
            "application_id is not in the finding's harmed_application_ids",
        )
    if amount_cents > cap["remaining_cents"]:
        raise err(
            "ERR_CAP_BUDGET_EXCEEDED",
            "Manual payment amount exceeds CAP remaining_cents",
        )
    rec = db.new_record(
        {
            "corrective_action_plan_id": cap["id"],
            "application_id": application_id,
            "amount_cents": amount_cents,
            "origin": "MANUAL",
            "status": "PENDING",
            "disbursed_by_user_id": None,
            "disposition_reason": None,
        }
    )
    db.STORES["payments"][rec["id"]] = rec
    cap_rollup(cap)
    db.touch(cap)
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/remediation-payments")
@require_roles(*ROLES)
def list_payments():
    page, total, limit, offset = list_page(
        "payments",
        {
            "corrective_action_plan_id": request.args.get("corrective_action_plan_id"),
            "application_id": request.args.get("application_id"),
            "status": request.args.get("status"),
        },
    )
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/remediation-payments/<paymentId>")
@require_roles(*ROLES)
def get_payment(paymentId):
    rec = get_or_404("payments", paymentId, "RemediationPayment")
    return success_obj(db.public(rec))


def _load(paymentId):
    rec = get_or_404("payments", paymentId, "RemediationPayment")
    return rec


def _cap_of(rec):
    cap = db.STORES["caps"].get(rec["corrective_action_plan_id"])
    if cap is None:
        raise err("ERR_NOT_FOUND", "CorrectiveActionPlan does not exist")
    return cap


@bp.post("/fair-lending/remediation-payments/<paymentId>/disburse")
@require_roles("RemediationSpecialist")
def disburse(paymentId):
    rec = _load(paymentId)
    cap = _cap_of(rec)
    # SoD (identity-level, priority 3): disburser must differ from the CAP
    # approver.
    if cap.get("approved_by_user_id") is not None and cap[
        "approved_by_user_id"
    ] == g.user_id:
        raise err(
            "ERR_SOD_VIOLATION",
            "Disbursing specialist must differ from the CAP approver",
        )
    if rec["status"] in ("VOIDED", "RETURNED"):
        raise already_terminal("RemediationPayment is in terminal state %s" % rec["status"])
    if rec["status"] != "PENDING":
        raise invalid_state("RemediationPayment is not PENDING")
    if cap["status"] not in ("EXECUTING", "OVERDUE"):
        raise err(
            "ERR_CAP_NOT_EXECUTING",
            "Payment operation requires CAP in EXECUTING or OVERDUE",
        )
    rec["status"] = "DISBURSED"
    rec["disbursed_by_user_id"] = g.user_id
    db.touch(rec)
    cap_rollup(cap)
    db.touch(cap)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/remediation-payments/<paymentId>/void")
@require_roles("RemediationSpecialist")
def void(paymentId):
    rec = _load(paymentId)
    cap = _cap_of(rec)
    if rec["status"] in ("VOIDED", "RETURNED"):
        raise already_terminal("RemediationPayment is in terminal state %s" % rec["status"])
    if rec["status"] != "PENDING":
        raise invalid_state("RemediationPayment is not PENDING")
    data = body()
    rec["status"] = "VOIDED"
    rec["disposition_reason"] = data.get("reason")
    db.touch(rec)
    # Compensating: amount returns to remaining funds.
    cap_rollup(cap)
    db.touch(cap)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/remediation-payments/<paymentId>/mark-returned")
@require_roles("RemediationSpecialist")
def mark_returned(paymentId):
    rec = _load(paymentId)
    cap = _cap_of(rec)
    if rec["status"] in ("VOIDED", "RETURNED"):
        raise already_terminal("RemediationPayment is in terminal state %s" % rec["status"])
    if rec["status"] != "DISBURSED":
        raise invalid_state("Only a DISBURSED payment can be marked returned")
    data = body()
    rec["status"] = "RETURNED"
    rec["disposition_reason"] = data.get("reason")
    db.touch(rec)
    # Compensating: funds clawed back to the pool.
    cap_rollup(cap)
    db.touch(cap)
    return success_obj(db.public(rec))
