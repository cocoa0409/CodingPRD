"""Loan routes: fetch, list, post payment, forbearance, delinquency, charge-off.

PRD §3.9 (payments/accrual/waterfall), §3.10 (release eligibility),
§3.11 (forbearance/delinquency/charge-off).
"""
from datetime import timedelta

from flask import Blueprint, request

import calc
import db
import serialize
import clock
from auth import authorize
from constants import COSIGNER_RELEASE_STREAK, FORBEARANCE_REASONS, GRACE_DAYS
from errors import err
from response import object_response, array_response
from store_helpers import get_or_404, sorted_by_created, paginate, append_audit
from timeutil import iso_z, parse_iso
from validate import (
    get_json_body,
    require_str,
    require_positive_int,
    require_int,
    require_enum,
    parse_pagination,
)

bp = Blueprint("loans", __name__)


def _consented_cosigner(application_id):
    for c in db.cosigners.values():
        if c["application_id"] == application_id and c["consent_status"] == "CONSENTED":
            return c
    return None


def _active_forbearance(loan_id):
    for p in db.forbearance_plans.values():
        if p["loan_id"] == loan_id and p["status"] == "ACTIVE":
            return p
    return None


@bp.route("/loans/<rid>", methods=["GET"])
def get_loan(rid):
    authorize(("GET", "/loans/{id}"))
    record = get_or_404(db.loans, rid)
    return object_response(serialize.loan(record), 200)


@bp.route("/loans", methods=["GET"])
def list_loans():
    authorize(("GET", "/loans"))
    limit, offset = parse_pagination()
    f_app = request.args.get("application_id")
    f_pool = request.args.get("abs_pool_id")
    f_status = request.args.get("repayment_status")
    records = list(db.loans.values())
    if f_app is not None:
        records = [r for r in records if r["application_id"] == f_app]
    if f_pool is not None:
        records = [r for r in records if r["abs_pool_id"] == f_pool]
    if f_status is not None:
        records = [r for r in records if r["repayment_status"] == f_status]
    records = sorted_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serialize.loan(r) for r in page], limit, offset, total)


@bp.route("/loans/<rid>/payments", methods=["POST"])
def post_payment(rid):
    user_id, role = authorize(("POST", "/loans/{id}/payments"))
    body = get_json_body()
    amount_cents = require_positive_int(body, "amount_cents")
    due_date_raw = require_str(body, "due_date")
    due_date_dt = parse_iso(due_date_raw)
    # paid_at optional; when omitted, stamp with the current clock (PRD §3.9).
    if "paid_at" in body and body.get("paid_at") is not None:
        paid_at_dt = parse_iso(require_str(body, "paid_at"))
    else:
        paid_at_dt = clock.now()

    with db.lock():
        loan = get_or_404(db.loans, rid)

        # Record repayment_status before applying the chain (for transitions).
        prior_status = loan["repayment_status"]

        # Step 1: accrue interest from last_accrual_at to paid_at.
        days = calc.floor_days_between(loan["last_accrual_at_dt"], paid_at_dt)
        new_interest = calc.accrue_interest_cents(
            loan["principal_balance_cents"], loan["locked_apr_bps"], days
        )
        loan["accrued_interest_cents"] += new_interest
        loan["last_accrual_at_dt"] = paid_at_dt
        loan["last_accrual_at"] = iso_z(paid_at_dt)

        # Step 2: waterfall — interest-first allocation.
        interest_portion, principal_portion = calc.waterfall(
            amount_cents, loan["accrued_interest_cents"], loan["principal_balance_cents"]
        )
        loan["accrued_interest_cents"] -= interest_portion
        loan["principal_balance_cents"] -= principal_portion

        # Step 3: on-time determination.
        grace_boundary = due_date_dt + timedelta(days=GRACE_DAYS)
        on_time = paid_at_dt <= grace_boundary

        cosigner = _consented_cosigner(loan["application_id"])
        if on_time and prior_status == "CURRENT":
            if cosigner is not None:
                cosigner["on_time_streak"] += 1
                db.touch(cosigner)
        else:
            # Late payment OR payment while not CURRENT resets the streak.
            if cosigner is not None and cosigner["on_time_streak"] != 0:
                cosigner["on_time_streak"] = 0
                db.touch(cosigner)

        # Persist the Payment record.
        payment = {
            "loan_id": loan["id"],
            "amount_cents": amount_cents,
            "due_date": iso_z(due_date_dt),
            "paid_at": iso_z(paid_at_dt),
            "on_time": on_time,
            "interest_portion_cents": interest_portion,
            "principal_portion_cents": principal_portion,
        }
        db.stamp_create(payment)
        db.payments[payment["id"]] = payment

        # Step 4: cosigner-release eligibility (independent dimension, PRD §3.10).
        # Evaluated against repayment_status CURRENT.
        if (
            loan["cosigner_release_status"] == "PENDING"
            and cosigner is not None
            and loan["repayment_status"] == "CURRENT"
            and cosigner["on_time_streak"] >= COSIGNER_RELEASE_STREAK
        ):
            loan["cosigner_release_status"] = "ELIGIBLE"
            db.touch(loan)
            append_audit("LOAN", loan["id"], "COSIGNER_RELEASE_ELIGIBLE", role, user_id)

        # Step 5: repayment-status transitions driven by the payment.
        # Cure: if loan was DELINQUENT, a posted payment returns it to CURRENT.
        if prior_status == "DELINQUENT":
            loan["repayment_status"] = "CURRENT"
            db.touch(loan)
            append_audit("LOAN", loan["id"], "LOAN_CURED", role, user_id)
        # Payoff: balances zeroed while CURRENT -> PAID_OFF.
        if (
            loan["repayment_status"] == "CURRENT"
            and loan["principal_balance_cents"] == 0
            and loan["accrued_interest_cents"] == 0
        ):
            loan["repayment_status"] = "PAID_OFF"
            if loan["cosigner_release_status"] == "PENDING":
                loan["cosigner_release_status"] = "NOT_APPLICABLE"
            db.touch(loan)
            append_audit("LOAN", loan["id"], "LOAN_PAID_OFF", role, user_id)

    return object_response(serialize.payment(payment), 201)


@bp.route("/loans/<rid>/payments", methods=["GET"])
def list_payments(rid):
    authorize(("GET", "/loans/{id}/payments"))
    limit, offset = parse_pagination()
    get_or_404(db.loans, rid)
    records = [p for p in db.payments.values() if p["loan_id"] == rid]
    records = sorted_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serialize.payment(r) for r in page], limit, offset, total)


@bp.route("/loans/<rid>/forbearance", methods=["POST"])
def forbearance(rid):
    user_id, role = authorize(("POST", "/loans/{id}/forbearance"))
    body = get_json_body()
    reason_code = require_enum(body, "reason_code", FORBEARANCE_REASONS)
    months_requested = require_int(body, "months_requested")

    with db.lock():
        loan = get_or_404(db.loans, rid)
        # State: defined only from CURRENT (PRD §3.11).
        if loan["repayment_status"] != "CURRENT":
            raise err("ERR_INVALID_STATE", "forbearance only from CURRENT")
        # An ACTIVE plan already existing -> ERR_FORBEARANCE_ALREADY_ACTIVE.
        if _active_forbearance(loan["id"]) is not None:
            raise err("ERR_FORBEARANCE_ALREADY_ACTIVE", "active forbearance plan exists")
        # months_requested between 1 and 12 inclusive.
        if months_requested < 1 or months_requested > 12:
            raise err("ERR_FORBEARANCE_TERM_INVALID", "months_requested out of range")

        plan = {
            "loan_id": loan["id"],
            "reason_code": reason_code,
            "months_requested": months_requested,
            "interest_capitalized_cents": 0,
            "status": "ACTIVE",
        }
        db.stamp_create(plan)
        db.forbearance_plans[plan["id"]] = plan

        loan["repayment_status"] = "FORBEARANCE"
        db.touch(loan)
        append_audit("LOAN", loan["id"], "LOAN_FORBEARANCE_STARTED", role, user_id)
    return object_response(serialize.forbearance_plan(plan), 201)


@bp.route("/loans/<rid>/mark-delinquent", methods=["POST"])
def mark_delinquent(rid):
    user_id, role = authorize(("POST", "/loans/{id}/mark-delinquent"))
    with db.lock():
        loan = get_or_404(db.loans, rid)
        if loan["repayment_status"] != "CURRENT":
            raise err("ERR_INVALID_STATE", "mark-delinquent only from CURRENT")
        loan["repayment_status"] = "DELINQUENT"
        # Reset the cosigner's streak if a CONSENTED cosigner exists.
        cosigner = _consented_cosigner(loan["application_id"])
        if cosigner is not None and cosigner["on_time_streak"] != 0:
            cosigner["on_time_streak"] = 0
            db.touch(cosigner)
        # If release dimension was ELIGIBLE, revert to PENDING.
        if loan["cosigner_release_status"] == "ELIGIBLE":
            loan["cosigner_release_status"] = "PENDING"
        db.touch(loan)
        append_audit("LOAN", loan["id"], "LOAN_DELINQUENT", role, user_id)
    return object_response(serialize.loan(loan), 200)


@bp.route("/loans/<rid>/charge-off", methods=["POST"])
def charge_off(rid):
    user_id, role = authorize(("POST", "/loans/{id}/charge-off"))
    with db.lock():
        loan = get_or_404(db.loans, rid)
        if loan["repayment_status"] != "DELINQUENT":
            raise err("ERR_INVALID_STATE", "charge-off only from DELINQUENT")
        loan["repayment_status"] = "CHARGED_OFF"
        loan["cosigner_release_status"] = "NOT_APPLICABLE"
        db.touch(loan)
        append_audit("LOAN", loan["id"], "LOAN_CHARGED_OFF", role, user_id)
    return object_response(serialize.loan(loan), 200)
