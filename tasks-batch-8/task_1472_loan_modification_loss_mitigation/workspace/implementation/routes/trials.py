from flask import Blueprint, request

import clock
import store
from auth import ALL_ROLES, NON_BORROWER_ROLES, authenticate, authorize, check_borrower_ownership
from errors import (
    ERR_LOAN_FORECLOSURE_COMPLETED,
    ERR_PAYMENT_AMOUNT_INVALID,
    ERR_TRIAL_PAYMENT_NOT_FOUND,
    ERR_TRIAL_PAYMENT_RESOLVED,
    ERR_TRIAL_PLAN_NOT_ACTIVE,
    ERR_TRIAL_PLAN_NOT_FOUND,
    ERR_TRIAL_PLAN_NOT_OFFERED,
    raise_err,
)
from services import (
    complete_plan,
    fail_plan,
    foreclosure_status_of,
    loan_of_payment,
    loan_of_plan,
    payment_out,
    plan_out,
)
from util import body_json, bump, get_or_404, list_response, req_int, success_object

bp = Blueprint("trials", __name__)


@bp.route("/trial-plans/<rid>/accept", methods=["POST"])
def accept_trial_plan(rid):
    uid, role = authenticate()
    authorize(role, ["Borrower"])
    plan = get_or_404(store.plans, rid, ERR_TRIAL_PLAN_NOT_FOUND, "TrialPaymentPlan")
    loan = loan_of_plan(plan)
    check_borrower_ownership(uid, loan)

    if plan["status"] != "OFFERED" or clock.now() > plan["offer_deadline"]:
        raise_err(ERR_TRIAL_PLAN_NOT_OFFERED,
                  "Trial plan is not OFFERED (or offer deadline has passed)")
    if foreclosure_status_of(loan) == "SALE_COMPLETED":
        raise_err(ERR_LOAN_FORECLOSURE_COMPLETED,
                  "Loan foreclosure sale is completed; workout dimension is locked")

    plan["status"] = "ACTIVE"
    plan["accepted_at"] = clock.now()
    bump(plan)
    app = store.applications[plan["application_id"]]
    if app["status"] == "EVALUATED_OFFER":
        app["status"] = "TRIAL_ACTIVE"
        bump(app)
    if loan["workout_status"] == "LOSS_MIT_REVIEW":
        loan["workout_status"] = "TRIAL"
        bump(loan)
    return success_object(plan_out(plan))


@bp.route("/trial-plans/<rid>", methods=["GET"])
def get_trial_plan(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    plan = get_or_404(store.plans, rid, ERR_TRIAL_PLAN_NOT_FOUND, "TrialPaymentPlan")
    return success_object(plan_out(plan))


@bp.route("/trial-plans", methods=["GET"])
def list_trial_plans():
    _, role = authenticate()
    authorize(role, NON_BORROWER_ROLES)
    records = list(store.plans.values())
    application_id = request.args.get("application_id")
    evaluation_id = request.args.get("evaluation_id")
    status = request.args.get("status")
    if application_id is not None:
        records = [p for p in records if p["application_id"] == application_id]
    if evaluation_id is not None:
        records = [p for p in records if p["evaluation_id"] == evaluation_id]
    if status is not None:
        records = [p for p in records if p["status"] == status]
    return list_response(records, plan_out)


@bp.route("/trial-plans/<rid>/payments", methods=["GET"])
def list_plan_payments(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    plan = get_or_404(store.plans, rid, ERR_TRIAL_PLAN_NOT_FOUND, "TrialPaymentPlan")
    records = [p for p in store.payments.values() if p["trial_plan_id"] == plan["id"]]
    return list_response(records, payment_out)


@bp.route("/trial-payments/<rid>/pay", methods=["POST"])
def pay_trial_payment(rid):
    uid, role = authenticate()
    authorize(role, ["Borrower"])
    body = body_json()
    amount_cents = req_int(body, "amount_cents")

    payment = get_or_404(store.payments, rid, ERR_TRIAL_PAYMENT_NOT_FOUND, "TrialPayment")
    plan = store.plans[payment["trial_plan_id"]]
    loan = loan_of_payment(payment)
    check_borrower_ownership(uid, loan)

    # state preconditions (priority 7)
    if plan["status"] != "ACTIVE":
        raise_err(ERR_TRIAL_PLAN_NOT_ACTIVE, "Trial plan is not ACTIVE")
    if payment["status"] != "SCHEDULED":
        raise_err(ERR_TRIAL_PAYMENT_RESOLVED,
                  "Trial payment already resolved (%s)" % payment["status"])
    # fiscal check (priority 11)
    if amount_cents <= 0:
        raise_err(ERR_PAYMENT_AMOUNT_INVALID, "amount_cents must be > 0")

    # resolution (PRD 3.7): insufficient -> late -> on-time; boundary inclusive
    if amount_cents < payment["scheduled_amount_cents"]:
        resolution = "PAID_INSUFFICIENT"
    elif clock.today() > payment["due_date"]:
        resolution = "PAID_LATE"
    else:
        resolution = "PAID_ON_TIME"

    payment["status"] = resolution
    payment["paid_at"] = clock.now()
    payment["received_amount_cents"] = amount_cents
    bump(payment)

    # suspense accrues identically for on-time, late, and insufficient payments
    plan["suspense_total_cents"] += amount_cents
    bump(plan)
    loan["suspense_cents"] += amount_cents
    bump(loan)

    siblings = [p for p in store.payments.values() if p["trial_plan_id"] == plan["id"]]
    if resolution in ("PAID_LATE", "PAID_INSUFFICIENT"):
        fail_plan(plan)
    elif resolution == "PAID_ON_TIME" and all(p["status"] == "PAID_ON_TIME" for p in siblings):
        complete_plan(plan)
    return success_object(payment_out(payment))


@bp.route("/trial-plans/<rid>/finalize", methods=["POST"])
def finalize_trial_plan(rid):
    _, role = authenticate()
    authorize(role, ["ServicingOps"])
    plan = get_or_404(store.plans, rid, ERR_TRIAL_PLAN_NOT_FOUND, "TrialPaymentPlan")
    if plan["status"] != "ACTIVE":
        raise_err(ERR_TRIAL_PLAN_NOT_ACTIVE, "Trial plan is not ACTIVE")

    today = clock.today()
    payments = sorted(
        [p for p in store.payments.values() if p["trial_plan_id"] == plan["id"]],
        key=lambda p: p["period_index"],
    )
    missed_any = False
    for p in payments:
        if p["status"] == "SCHEDULED" and p["due_date"] < today:
            p["status"] = "MISSED"
            bump(p)
            missed_any = True

    if missed_any:
        fail_plan(plan)
    elif all(p["status"] == "PAID_ON_TIME" for p in payments):
        complete_plan(plan)
    return success_object(plan_out(plan))
