"""Payment plans, installment schedules, cash application and reversal."""

from datetime import timedelta

from flask import Blueprint

import calc
import clock
import db
import middleware as mw
import response
import services
import validate
from errors import err
from middleware import (COMPLIANCE_AUDITOR, DISCLOSURE_OFFICER,
                        PROGRAM_ADMINISTRATOR, TAXPAYER)

bp = Blueprint("payments", __name__)

READERS = [PROGRAM_ADMINISTRATOR, DISCLOSURE_OFFICER, COMPLIANCE_AUDITOR, TAXPAYER]


# =============================================================================
# payment plans
# =============================================================================
@bp.post("/amnesty/payment-plans")
def propose_plan():
    user_id, role = mw.identity([TAXPAYER])
    body = validate.get_body()
    agreement = mw.body_fk(body, "agreement_id", db.agreements, "ERR_AGREEMENT_NOT_FOUND")
    if agreement is not None:
        mw.require_agreement_owner(agreement, user_id, role)

    agreement_id = validate.vid(body, "agreement_id")
    expected_version = validate.vint(body, "expected_agreement_version")
    plan_type = validate.venum(body, "plan_type", validate.PLAN_TYPES)
    installment_count = validate.vint(body, "installment_count")
    down_payment = validate.vint(body, "down_payment_cents", minimum=0)

    if expected_version != agreement["version"]:
        raise err("ERR_STALE_AGREEMENT_VERSION")
    if agreement["status"] != "EXECUTED":
        raise err("ERR_AGREEMENT_NOT_EXECUTED")

    program = services.program_of(agreement)
    if installment_count < 1 or installment_count > program["installment_max_count"]:
        raise err("ERR_INVALID_INSTALLMENT_COUNT")
    if plan_type == "LUMP_SUM" and installment_count != 1:
        raise err("ERR_INVALID_INSTALLMENT_COUNT")
    if down_payment < calc.min_down_payment_cents(agreement["total_due_cents"]):
        raise err("ERR_DOWN_PAYMENT_BELOW_MINIMUM")

    for plan in services.agreement_plans(agreement_id):
        if plan["status"] == "PROPOSED":
            plan["status"] = "SUPERSEDED"
            db.touch(plan)

    rec = db.insert(db.payment_plans, {
        "agreement_id": agreement_id,
        "plan_type": plan_type,
        "installment_count": installment_count,
        "down_payment_cents": down_payment,
        "scheduled_total_cents": 0,
        "status": "PROPOSED",
        "approved_at": None,
        "rejection_reason": None,
        "default_reason": None,
        "proposed_by_user_id": user_id,
    })
    db.touch(agreement)
    return response.created(services.plan_out(rec))


@bp.get("/amnesty/payment-plans/<plan_id>")
def read_plan(plan_id):
    user_id, role = mw.identity(READERS)
    plan = mw.find(db.payment_plans, plan_id, "ERR_PAYMENT_PLAN_NOT_FOUND")
    mw.require_agreement_owner(db.agreements[plan["agreement_id"]], user_id, role)
    return response.ok(services.plan_out(plan))


@bp.post("/amnesty/payment-plans/<plan_id>/approve")
def approve_plan(plan_id):
    mw.identity([DISCLOSURE_OFFICER])
    plan = mw.find(db.payment_plans, plan_id, "ERR_PAYMENT_PLAN_NOT_FOUND")
    agreement = db.agreements[plan["agreement_id"]]
    program = services.program_of(agreement)

    services.check_program_open(program)
    if agreement["status"] != "EXECUTED":
        raise err("ERR_AGREEMENT_NOT_EXECUTED")
    if plan["status"] != "PROPOSED":
        raise err("ERR_PLAN_NOT_PROPOSED")
    services.check_window_live(program)

    approved_at = clock.now()
    anchor = approved_at.date()
    count = plan["installment_count"]
    schedulable = agreement["total_due_cents"] - plan["down_payment_cents"]
    amounts = calc.schedule_amounts(schedulable, count)
    due_dates = [anchor + timedelta(days=calc.INSTALLMENT_PERIOD_DAYS * k)
                 for k in range(1, count + 1)]

    # both guards run before a single installment row is written
    horizon = program["_close_dt"].date() + timedelta(days=calc.INSTALLMENT_HORIZON_DAYS)
    if due_dates[-1] > horizon:
        raise err("ERR_INSTALLMENT_HORIZON_EXCEEDED")
    if min(amounts) < calc.MIN_INSTALLMENT_CENTS:
        raise err("ERR_INSTALLMENT_BELOW_MINIMUM")
    if agreement["paid_total_cents"] < plan["down_payment_cents"]:
        raise err("ERR_DOWN_PAYMENT_NOT_RECEIVED")

    for index in range(count):
        db.insert(db.installments, {
            "payment_plan_id": plan["id"],
            "seq_index": index + 1,
            "due_date": due_dates[index].isoformat(),
            "amount_cents": amounts[index],
            "paid_cents": 0,
            "status": "SCHEDULED",
        })

    plan["status"] = "ACTIVE"
    plan["approved_at"] = clock.iso(approved_at)
    plan["scheduled_total_cents"] = sum(amounts)
    db.touch(plan)

    agreement["unapplied_credit_cents"] -= plan["down_payment_cents"]
    agreement["down_payment_applied_cents"] += plan["down_payment_cents"]
    services.recompute_payment_status(agreement)
    db.touch(agreement)
    return response.ok(services.plan_out(plan))


@bp.post("/amnesty/payment-plans/<plan_id>/reject")
def reject_plan(plan_id):
    mw.identity([DISCLOSURE_OFFICER])
    plan = mw.find(db.payment_plans, plan_id, "ERR_PAYMENT_PLAN_NOT_FOUND")
    body = validate.get_body()
    rejection_reason = validate.vstr(body, "rejection_reason")
    if plan["status"] != "PROPOSED":
        raise err("ERR_PLAN_NOT_PROPOSED")
    plan["status"] = "REJECTED"
    plan["rejection_reason"] = rejection_reason
    db.touch(plan)
    return response.ok(services.plan_out(plan))


@bp.post("/amnesty/payment-plans/<plan_id>/default")
def default_plan(plan_id):
    mw.identity([COMPLIANCE_AUDITOR])
    plan = mw.find(db.payment_plans, plan_id, "ERR_PAYMENT_PLAN_NOT_FOUND")
    body = validate.get_body()
    default_reason = validate.vstr(body, "default_reason")
    if plan["status"] != "ACTIVE":
        raise err("ERR_PLAN_NOT_ACTIVE")
    services.default_plan(plan, db.agreements[plan["agreement_id"]], default_reason)
    return response.ok(services.plan_out(plan))


@bp.get("/amnesty/payment-plans/<plan_id>/installments")
def list_installments(plan_id):
    user_id, role = mw.identity(READERS)
    plan = mw.find(db.payment_plans, plan_id, "ERR_PAYMENT_PLAN_NOT_FOUND")
    mw.require_agreement_owner(db.agreements[plan["agreement_id"]], user_id, role)
    limit, offset = response.pagination()
    rows = mw.filter_equals(services.plan_installments(plan_id), "status")
    return response.paginate(rows, limit, offset, services.installment_out)


@bp.get("/amnesty/installments/<installment_id>")
def read_installment(installment_id):
    user_id, role = mw.identity(READERS)
    installment = mw.find(db.installments, installment_id, "ERR_INSTALLMENT_NOT_FOUND")
    plan = db.payment_plans[installment["payment_plan_id"]]
    mw.require_agreement_owner(db.agreements[plan["agreement_id"]], user_id, role)
    return response.ok(services.installment_out(installment))


# =============================================================================
# payments
# =============================================================================
@bp.post("/amnesty/payments")
def create_payment():
    user_id, role = mw.identity([TAXPAYER])
    body = validate.get_body()
    agreement = mw.body_fk(body, "agreement_id", db.agreements, "ERR_AGREEMENT_NOT_FOUND")
    if agreement is not None:
        mw.require_agreement_owner(agreement, user_id, role)

    agreement_id = validate.vid(body, "agreement_id")
    amount = validate.vint(body, "amount_cents", minimum=1)
    reference = validate.vstr(body, "payment_reference", required=False, allow_blank=True)

    if agreement["status"] != "EXECUTED":
        raise err("ERR_AGREEMENT_NOT_EXECUTED")

    # the ceiling is dormant until the agreement carries a filed return
    measurable = [r for r in services.agreement_returns(agreement_id)
                  if r["status"] in services.TOTAL_QUALIFYING]
    if measurable and amount > agreement["total_due_cents"] - agreement["paid_total_cents"]:
        raise err("ERR_PAYMENT_EXCEEDS_BALANCE")

    rec = db.insert(db.payments, {
        "agreement_id": agreement_id,
        "amount_cents": amount,
        "payment_reference": reference,
        "received_at": clock.now_iso(),
        "status": "APPLIED",
        "allocations": [],
        "unapplied_delta_cents": 0,
        "reversal_reason": None,
    })
    services.apply_payment(agreement, rec)
    return response.created(services.payment_out(rec))


@bp.get("/amnesty/agreements/<agreement_id>/payment-plans")
def list_agreement_plans(agreement_id):
    user_id, role = mw.identity(READERS)
    agreement = mw.find(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    mw.require_agreement_owner(agreement, user_id, role)
    limit, offset = response.pagination()
    rows = mw.filter_equals(services.agreement_plans(agreement_id), "status")
    return response.paginate(rows, limit, offset, services.plan_out)


@bp.get("/amnesty/agreements/<agreement_id>/payments")
def list_agreement_payments(agreement_id):
    user_id, role = mw.identity(READERS)
    agreement = mw.find(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    mw.require_agreement_owner(agreement, user_id, role)
    limit, offset = response.pagination()
    rows = mw.filter_equals(services.agreement_payments(agreement_id), "status")
    return response.paginate(rows, limit, offset, services.payment_out)


@bp.get("/amnesty/payments/<payment_id>")
def read_payment(payment_id):
    user_id, role = mw.identity(READERS)
    payment = mw.find(db.payments, payment_id, "ERR_PAYMENT_NOT_FOUND")
    mw.require_agreement_owner(db.agreements[payment["agreement_id"]], user_id, role)
    return response.ok(services.payment_out(payment))


@bp.post("/amnesty/payments/<payment_id>/reverse")
def reverse_payment(payment_id):
    mw.identity([PROGRAM_ADMINISTRATOR])
    payment = mw.find(db.payments, payment_id, "ERR_PAYMENT_NOT_FOUND")
    body = validate.get_body()
    reversal_reason = validate.vstr(body, "reversal_reason")

    if payment["status"] != "APPLIED":
        raise err("ERR_PAYMENT_NOT_APPLIED")
    agreement = db.agreements[payment["agreement_id"]]
    if agreement["status"] == "FULFILLED":
        raise err("ERR_AGREEMENT_NOT_EXECUTED")
    if (agreement["paid_total_cents"] - payment["amount_cents"]
            < agreement["down_payment_applied_cents"]):
        raise err("ERR_REVERSAL_BREAKS_DOWN_PAYMENT")

    services.reverse_payment(agreement, payment, reversal_reason)
    return response.ok(services.payment_out(payment))
