"""Payroll remittance endpoints: post (waterfall allocation), list, reverse."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles, check_participant_ownership, paginate
from response import success_object, success_list
from services import audit
from services import calculations as calc
from services.calculations import eligible_loans_for_remittance
from services.state import (get_participant, get_remittance, plan_of_participant,
                            require_plan_active, evaluate_loan_after_remittance,
                            recompute_loan_outstanding)
from services.util import new_id, now_iso, today, touch, parse, iso, date_iso, last_day_of_next_quarter

bp = Blueprint("remittances", __name__)


def _bad(msg):
    return errors.err(errors.ERR_INVALID_REQUEST, msg, 400)


def _apply_waterfall(loans, amount_cents, per_loan_cap=None):
    """Apply funds across candidates in pinned order.

    Returns (applied_allocations, remaining).
    per_loan_cap: optional dict loan_id -> cap for explicit allocations.
    """
    applied = []
    remaining = amount_cents
    candidates = calc.waterfall_candidates(loans)
    for loan, inst in candidates:
        if remaining <= 0:
            break
        if per_loan_cap is not None:
            cap_left = per_loan_cap.get(loan["id"], 0)
            if cap_left <= 0:
                continue
            apply_amt = min(remaining, cap_left,
                            inst["scheduled_amount_cents"] - inst["paid_amount_cents"])
        else:
            apply_amt = min(remaining,
                            inst["scheduled_amount_cents"] - inst["paid_amount_cents"])
        if apply_amt <= 0:
            continue
        to_interest, to_principal = calc.apply_to_installment(inst, apply_amt)
        applied.append({
            "loan_id": loan["id"],
            "installment_id": inst["id"],
            "amount_cents": apply_amt,
            "to_interest_cents": to_interest,
            "to_principal_cents": to_principal,
        })
        remaining -= apply_amt
        if per_loan_cap is not None:
            per_loan_cap[loan["id"]] -= apply_amt
    return applied, remaining


@bp.route("/participants/<participant_id>/remittances", methods=["POST"])
def post_remittance(participant_id):
    user_id, role = require_roles("PayrollProvider", "RecordkeeperAdmin")
    participant = get_participant(participant_id)
    plan = plan_of_participant(participant)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise _bad("Body must be a JSON object")
    amount = body.get("amount_cents")
    pay_date = body.get("pay_date")
    allocations = body.get("allocations")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise _bad("amount_cents is required and must be a positive integer")
    if not isinstance(pay_date, str):
        raise _bad("pay_date is required and must be an ISO 8601 string")
    try:
        pay_date_dt = parse(pay_date)
    except Exception:
        raise _bad("pay_date must be a valid ISO 8601 timestamp")

    # Plan posture gate
    require_plan_active(plan)

    eligible = eligible_loans_for_remittance(participant["id"])
    if allocations is not None:
        if not isinstance(allocations, list):
            raise _bad("allocations must be a list")
        cleaned = []
        for a in allocations:
            if not isinstance(a, dict):
                raise _bad("each allocation must be an object")
            lid = a.get("loan_id")
            amt = a.get("amount_cents")
            if not isinstance(lid, str):
                raise _bad("allocation loan_id must be a string")
            if not isinstance(amt, int) or isinstance(amt, bool) or amt < 0:
                raise _bad("allocation amount_cents must be a non-negative integer")
            cleaned.append((lid, amt))
        # sum must equal amount
        if sum(amt for _, amt in cleaned) != amount:
            raise errors.err(errors.ERR_REMITTANCE_AMOUNT_MISMATCH,
                             "Explicit allocations must sum to amount_cents", 422)
        # each loan must be eligible
        eligible_ids = {l["id"] for l in eligible}
        for lid, _ in cleaned:
            if lid not in eligible_ids:
                raise errors.err(errors.ERR_INVALID_STATE,
                                 f"Loan {lid} is not eligible for remittance application", 409)
        # apply per loan in waterfall order with per-loan caps
        per_loan_cap = {}
        for lid, amt in cleaned:
            per_loan_cap[lid] = per_loan_cap.get(lid, 0) + amt
        # Ensure each referenced loan has enough candidate balance
        for lid, amt in per_loan_cap.items():
            loan = db.loans[lid]
            total_coverable = sum(
                i["scheduled_amount_cents"] - i["paid_amount_cents"]
                for i in calc.loan_installments(lid)
                if i["status"] in ("MISSED", "PENDING")
                and i["paid_amount_cents"] < i["scheduled_amount_cents"])
            if amt > total_coverable:
                raise errors.err(errors.ERR_REMITTANCE_AMOUNT_MISMATCH,
                                 "Allocation exceeds loan's remaining scheduled balance", 422)
        applied, remaining = _apply_waterfall(eligible, amount, per_loan_cap)
    else:
        if not eligible:
            raise errors.err(errors.ERR_INVALID_STATE,
                             "No eligible loans for remittance application", 409)
        candidates = calc.waterfall_candidates(eligible)
        if not candidates:
            raise errors.err(errors.ERR_INVALID_STATE,
                             "No candidate installments for remittance application", 409)
        total_coverable = sum(i["scheduled_amount_cents"] - i["paid_amount_cents"]
                              for _, i in candidates)
        if amount > total_coverable:
            raise errors.err(errors.ERR_REMITTANCE_AMOUNT_MISMATCH,
                             "Remittance overpays the remaining scheduled balance", 422)
        applied, remaining = _apply_waterfall(eligible, amount)

    remittance = {
        "id": new_id(),
        "participant_id": participant["id"],
        "amount_cents": amount,
        "pay_date": pay_date,
        "allocations": allocations,
        "applied_allocations": applied,
        "status": "POSTED",
    }
    remittance["created_at"] = now_iso()
    remittance["updated_at"] = remittance["created_at"]
    remittance["version"] = 1
    db.payroll_remittances[remittance["id"]] = remittance

    # Re-evaluate each affected loan
    affected_loan_ids = {a["loan_id"] for a in applied}
    for lid in affected_loan_ids:
        loan = db.loans[lid]
        evaluate_loan_after_remittance(loan, pay_date_dt)
        touch(loan)

    audit.append(plan["id"], role, user_id, "REMITTANCE_POSTED",
                 "PayrollRemittance", remittance["id"],
                 {"amount_cents": amount, "pay_date": pay_date})
    return success_object(remittance, status=201)


@bp.route("/participants/<participant_id>/remittances", methods=["GET"])
def list_remittances(participant_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor",
                                  "PayrollProvider", "Participant")
    participant = get_participant(participant_id)
    check_participant_ownership(user_id, role, participant["id"])
    items = sorted([r for r in db.payroll_remittances.values()
                    if r["participant_id"] == participant["id"]],
                   key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.route("/remittances/<remittance_id>/reverse", methods=["POST"])
def reverse_remittance(remittance_id):
    user_id, role = require_roles("RecordkeeperAdmin")
    remittance = get_remittance(remittance_id)
    participant = get_participant(remittance["participant_id"])
    plan = plan_of_participant(participant)
    if remittance["status"] != "POSTED":
        raise errors.err(errors.ERR_INVALID_STATE,
                         f"Cannot reverse a remittance in {remittance['status']}", 409)
    require_plan_active(plan)

    # Undo applied_allocations exactly
    affected_loan_ids = set()
    for alloc in remittance.get("applied_allocations") or []:
        inst = db.loan_installments.get(alloc["installment_id"])
        if inst is not None:
            inst["paid_amount_cents"] -= alloc["amount_cents"]
        affected_loan_ids.add(alloc["loan_id"])
    remittance["status"] = "REVERSED"
    touch(remittance)

    today_dt = today()
    for lid in affected_loan_ids:
        loan = db.loans.get(lid)
        if loan is None:
            continue
        recompute_loan_outstanding(loan)
        # REPAID -> DISBURSED revert
        was_repaid = loan["lifecycle_status"] == "REPAID"
        if was_repaid and (loan.get("outstanding_principal_cents") or 0) > 0:
            loan["lifecycle_status"] = "DISBURSED"
            # CLOSED rows with shortfall return to PENDING
            for inst in calc.loan_installments(loan["id"]):
                if inst["status"] == "CLOSED" and \
                        inst["paid_amount_cents"] < inst["scheduled_amount_cents"]:
                    inst["status"] = "PENDING"
        # Recompute installment statuses against the current clock
        for inst in calc.loan_installments(loan["id"]):
            if inst["status"] in ("REBUILT",):
                continue
            if inst["status"] == "PAID" and \
                    inst["paid_amount_cents"] < inst["scheduled_amount_cents"]:
                inst["status"] = "PENDING"
            if inst["status"] == "CURED" and \
                    inst["paid_amount_cents"] < inst["scheduled_amount_cents"]:
                inst["status"] = "MISSED"
            if inst["status"] == "PENDING" and \
                    inst["paid_amount_cents"] < inst["scheduled_amount_cents"] and \
                    parse(inst["due_date"]) < today_dt:
                inst["status"] = "MISSED"
        # Re-evaluate delinquency
        if loan["lifecycle_status"] == "DISBURSED" and \
                loan["delinquency_status"] != "DEEMED":
            earliest = calc.earliest_unpaid_missed_due_date(loan["id"])
            if earliest is not None:
                new_deadline = last_day_of_next_quarter(earliest)
                loan["delinquency_status"] = "DELINQUENT"
                loan["cure_deadline_on"] = date_iso(new_deadline)
            else:
                if loan["delinquency_status"] == "DELINQUENT":
                    loan["delinquency_status"] = "CURRENT"
                    loan["cure_deadline_on"] = None
        calc.recompute_accrued_unpaid_interest(loan, today_dt)
        touch(loan)

    audit.append(plan["id"], role, user_id, "REMITTANCE_REVERSED",
                 "PayrollRemittance", remittance["id"], {})
    return success_object(remittance)
