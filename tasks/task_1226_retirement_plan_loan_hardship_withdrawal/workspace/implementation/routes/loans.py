"""Loan endpoints: request, read, withdraw, disburse, refinance, schedule rebuild,
installments, refinances listing, approval tasks listing."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles, check_participant_ownership, paginate
from response import success_object, success_list
from services import audit
from services import calculations as calc
from services.state import (get_plan, get_participant, get_loan,
                            plan_of_participant, plan_of_loan,
                            require_plan_active, disburse_loan,
                            has_active_suspension)
from services.util import new_id, now_iso, today, touch, iso, parse, add_months

bp = Blueprint("loans", __name__)


def _bad(msg):
    return errors.err(errors.ERR_INVALID_REQUEST, msg, 400)


def _create_approval_tasks(plan, subject_type, subject_id, chain):
    for i, approver_role in enumerate(chain, start=1):
        task = {
            "id": new_id(),
            "plan_id": plan["id"],
            "subject_type": subject_type,
            "subject_id": subject_id,
            "step_order": i,
            "approver_role": approver_role,
            "status": "PENDING",
            "decided_by": None,
            "decided_on": None,
        }
        task["created_at"] = now_iso()
        task["updated_at"] = task["created_at"]
        task["version"] = 1
        db.approval_tasks[task["id"]] = task


@bp.route("/participants/<participant_id>/loans", methods=["POST"])
def request_loan(participant_id):
    user_id, role = require_roles("Participant")
    participant = get_participant(participant_id)
    check_participant_ownership(user_id, role, participant["id"])
    plan = plan_of_participant(participant)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise _bad("Body must be a JSON object")
    principal = body.get("principal_amount_cents")
    term = body.get("term_months")
    if not isinstance(principal, int) or isinstance(principal, bool):
        raise _bad("principal_amount_cents is required and must be an integer")
    if not isinstance(term, int) or isinstance(term, bool):
        raise _bad("term_months is required and must be an integer")

    # Plan posture gate (priority 8)
    require_plan_active(plan)

    today_dt = today()
    # Priority 10: suspension overlap
    if has_active_suspension(participant["id"], today_dt):
        raise errors.err(errors.ERR_SUSPENSION_OVERLAP,
                         "An ACTIVE suspension record exists for the participant", 422)

    # Priority 11: business constraints in pinned order
    if participant["employment_status"] != "ACTIVE":
        raise errors.err(errors.ERR_EMPLOYMENT_NOT_ACTIVE,
                         "Employment is not ACTIVE", 422)
    locked_until = participant.get("loan_eligibility_locked_until")
    if locked_until and today_dt < parse(locked_until):
        raise errors.err(errors.ERR_LOAN_ELIGIBILITY_LOCKED,
                         "Loan eligibility is locked", 422)
    open_count = calc.outstanding_loan_count(participant["id"])
    if open_count >= plan["max_loans_outstanding"]:
        raise errors.err(errors.ERR_MAX_LOANS_OUTSTANDING,
                         "Max loans outstanding reached", 422)
    if principal < plan["min_loan_amount_cents"]:
        raise errors.err(errors.ERR_LOAN_BELOW_MINIMUM,
                         "Principal below plan minimum", 422)
    if term > plan["max_term_months"]:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "term_months exceeds plan maximum", 400)

    # Priority 12: fiscal
    max_amt = calc.loan_maximum_amount(participant, plan, today_dt)
    if principal > max_amt:
        raise errors.err(errors.ERR_LOAN_LIMIT_EXCEEDED,
                         "Principal exceeds maximum loan amount", 422)

    loan = {
        "id": new_id(),
        "participant_id": participant["id"],
        "plan_id": plan["id"],
        "refinances_loan_id": None,
        "principal_amount_cents": principal,
        "term_months": term,
        "interest_rate_bps": plan["interest_rate_bps"],
        "day_count_convention": plan["day_count_convention"],
        "scheduled_payment_cents": None,
        "outstanding_principal_cents": None,
        "accrued_unpaid_interest_cents": 0,
        "lifecycle_status": "REQUESTED",
        "delinquency_status": "NONE",
        "disbursed_on": None,
        "cure_deadline_on": None,
        "deemed_on": None,
    }
    loan["created_at"] = now_iso()
    loan["updated_at"] = loan["created_at"]
    loan["version"] = 1
    db.loans[loan["id"]] = loan
    _create_approval_tasks(plan, "LOAN", loan["id"], plan["loan_approval_chain"])
    audit.append(plan["id"], role, user_id, "LOAN_REQUESTED", "Loan", loan["id"],
                 {"principal_amount_cents": principal, "term_months": term})
    return success_object(loan, status=201)


@bp.route("/participants/<participant_id>/loans", methods=["GET"])
def list_participant_loans(participant_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor", "Participant")
    participant = get_participant(participant_id)
    check_participant_ownership(user_id, role, participant["id"])
    items = sorted([l for l in db.loans.values() if l["participant_id"] == participant["id"]],
                   key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.route("/loans/<loan_id>", methods=["GET"])
def read_loan(loan_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor", "Participant")
    loan = get_loan(loan_id)
    check_participant_ownership(user_id, role, loan["participant_id"])
    return success_object(loan)


@bp.route("/loans/<loan_id>/withdraw", methods=["POST"])
def withdraw_loan(loan_id):
    user_id, role = require_roles("Participant")
    loan = get_loan(loan_id)
    check_participant_ownership(user_id, role, loan["participant_id"])
    if loan["lifecycle_status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE,
                         f"Cannot withdraw a loan in {loan['lifecycle_status']}", 409)
    loan["lifecycle_status"] = "WITHDRAWN"
    touch(loan)
    for task in db.approval_tasks.values():
        if task["subject_type"] == "LOAN" and task["subject_id"] == loan["id"] \
                and task["status"] == "PENDING":
            task["status"] = "CANCELLED"
            touch(task)
    return success_object(loan)


@bp.route("/loans/<loan_id>/disburse", methods=["POST"])
def disburse(loan_id):
    user_id, role = require_roles("RecordkeeperAdmin")
    loan = get_loan(loan_id)
    plan = plan_of_loan(loan)
    if loan["lifecycle_status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE,
                         f"Cannot disburse a loan in {loan['lifecycle_status']}", 409)
    require_plan_active(plan)
    disburse_loan(loan)
    touch(loan)
    audit.append(plan["id"], role, user_id, "LOAN_DISBURSED", "Loan", loan["id"],
                 {"disbursed_on": loan["disbursed_on"],
                  "scheduled_payment_cents": loan["scheduled_payment_cents"]})
    return success_object(loan)


@bp.route("/loans/<loan_id>/refinance", methods=["POST"])
def refinance(loan_id):
    user_id, role = require_roles("RecordkeeperAdmin")
    old_loan = get_loan(loan_id)
    plan = plan_of_loan(old_loan)
    participant = get_participant(old_loan["participant_id"])
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise _bad("Body must be a JSON object")
    cash_out = body.get("cash_out_cents")
    if not isinstance(cash_out, int) or isinstance(cash_out, bool) or cash_out < 0:
        raise _bad("cash_out_cents is required and must be a non-negative integer")

    # from-state
    if old_loan["lifecycle_status"] != "DISBURSED":
        raise errors.err(errors.ERR_INVALID_STATE,
                         f"Cannot refinance a loan in {old_loan['lifecycle_status']}", 409)
    # plan posture
    require_plan_active(plan)
    # allows_refinance
    if not plan["allows_refinance"]:
        raise errors.err(errors.ERR_REFINANCE_NOT_ALLOWED,
                         "Plan does not allow refinancing", 422)
    # delinquency != DEEMED
    if old_loan["delinquency_status"] == "DEEMED":
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Cannot refinance a DEEMED loan", 409)
    # lookback
    today_dt = today()
    lookback_threshold = add_months(today_dt, -plan["refinance_min_months_since_disbursement"])
    disbursed_dt = parse(old_loan["disbursed_on"])
    if disbursed_dt > lookback_threshold:
        raise errors.err(errors.ERR_REFINANCE_LOOKBACK_VIOLATION,
                         "Refinance lookback period not elapsed", 422)
    # new principal & fiscal gate
    new_principal = calc.refinance_new_principal(old_loan, cash_out, today_dt)
    max_amt = calc.loan_maximum_amount(participant, plan, today_dt)
    if new_principal > max_amt:
        raise errors.err(errors.ERR_LOAN_LIMIT_EXCEEDED,
                         "Refinance principal exceeds maximum loan amount", 422)

    # Link 1: old loan
    old_loan["outstanding_principal_cents"] = 0
    for inst in calc.loan_installments(old_loan["id"]):
        if inst["status"] == "PENDING":
            inst["status"] = "CLOSED"
    old_loan["delinquency_status"] = "NONE"
    old_loan["lifecycle_status"] = "REFINANCED"
    touch(old_loan)

    # Link 2: new loan, already DISBURSED
    new_loan = {
        "id": new_id(),
        "participant_id": participant["id"],
        "plan_id": plan["id"],
        "refinances_loan_id": old_loan["id"],
        "principal_amount_cents": new_principal,
        "term_months": old_loan["term_months"],
        "interest_rate_bps": old_loan["interest_rate_bps"],
        "day_count_convention": old_loan["day_count_convention"],
        "scheduled_payment_cents": None,
        "outstanding_principal_cents": None,
        "accrued_unpaid_interest_cents": 0,
        "lifecycle_status": "DISBURSED",
        "delinquency_status": "CURRENT",
        "disbursed_on": None,
        "cure_deadline_on": None,
        "deemed_on": None,
    }
    new_loan["created_at"] = now_iso()
    new_loan["updated_at"] = new_loan["created_at"]
    new_loan["version"] = 1
    db.loans[new_loan["id"]] = new_loan
    disburse_loan(new_loan)

    audit.append(plan["id"], role, user_id, "LOAN_REFINANCED", "Loan", old_loan["id"],
                 {"new_loan_id": new_loan["id"], "new_principal_cents": new_principal})
    audit.append(plan["id"], role, user_id, "LOAN_REFINANCED", "Loan", new_loan["id"],
                 {"old_loan_id": old_loan["id"], "new_principal_cents": new_principal})
    return success_object(new_loan, status=201)


@bp.route("/loans/<loan_id>/schedule/rebuild", methods=["POST"])
def rebuild_schedule(loan_id):
    user_id, role = require_roles("RecordkeeperAdmin")
    loan = get_loan(loan_id)
    plan = plan_of_loan(loan)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise _bad("Body must be a JSON object")
    if "expected_loan_version" not in body:
        raise _bad("expected_loan_version is required")
    if not isinstance(body["expected_loan_version"], int) or \
            isinstance(body["expected_loan_version"], bool):
        raise _bad("expected_loan_version must be an integer")
    term = body.get("term_months")
    if not isinstance(term, int) or isinstance(term, bool) or term <= 0:
        raise _bad("term_months is required and must be a positive integer")

    # from-state
    if loan["lifecycle_status"] != "DISBURSED":
        raise errors.err(errors.ERR_INVALID_STATE,
                         f"Cannot rebuild schedule for a loan in {loan['lifecycle_status']}", 409)
    # OCC
    if body["expected_loan_version"] != loan["version"]:
        raise errors.err(errors.ERR_STALE_VERSION,
                         "expected_loan_version does not match current loan version", 412)
    # plan posture
    require_plan_active(plan)

    # Supersede PENDING installments -> REBUILT
    installments = calc.loan_installments(loan["id"])
    superseded = [i for i in installments if i["status"] == "PENDING"]
    last_superseded_due = None
    if superseded:
        last_superseded_due = parse(superseded[-1]["due_date"])
    for inst in superseded:
        inst["status"] = "REBUILT"

    max_number = max((i["installment_number"] for i in installments), default=0)
    outstanding = loan.get("outstanding_principal_cents") or 0
    scheduled_payment, rows = calc.build_amortization_schedule(
        outstanding, loan["interest_rate_bps"], term,
        loan["day_count_convention"], parse(loan["disbursed_on"]),
        starting_installment_number=max_number + 1,
        first_due_date_dt=last_superseded_due)
    loan["scheduled_payment_cents"] = scheduled_payment
    for row in rows:
        inst = {
            "id": new_id(),
            "created_at": now_iso(),
            "loan_id": loan["id"],
            "installment_number": row["installment_number"],
            "due_date": row["due_date"],
            "scheduled_amount_cents": row["scheduled_amount_cents"],
            "principal_portion_cents": row["principal_portion_cents"],
            "interest_portion_cents": row["interest_portion_cents"],
            "paid_amount_cents": 0,
            "status": "PENDING",
        }
        db.loan_installments[inst["id"]] = inst
    touch(loan)
    return success_object(loan)


@bp.route("/loans/<loan_id>/installments", methods=["GET"])
def list_installments(loan_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor",
                                  "PayrollProvider", "Participant")
    loan = get_loan(loan_id)
    check_participant_ownership(user_id, role, loan["participant_id"])
    items = sorted([i for i in db.loan_installments.values() if i["loan_id"] == loan["id"]],
                   key=lambda r: r["installment_number"])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.route("/loans/<loan_id>/refinances", methods=["GET"])
def list_refinances(loan_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor", "Participant")
    loan = get_loan(loan_id)
    check_participant_ownership(user_id, role, loan["participant_id"])
    items = sorted([l for l in db.loans.values() if l.get("refinances_loan_id") == loan["id"]],
                   key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.route("/loans/<loan_id>/approval-tasks", methods=["GET"])
def list_loan_approval_tasks(loan_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor", "Participant")
    loan = get_loan(loan_id)
    check_participant_ownership(user_id, role, loan["participant_id"])
    items = sorted([t for t in db.approval_tasks.values()
                    if t["subject_type"] == "LOAN" and t["subject_id"] == loan["id"]],
                   key=lambda r: r["step_order"])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)
