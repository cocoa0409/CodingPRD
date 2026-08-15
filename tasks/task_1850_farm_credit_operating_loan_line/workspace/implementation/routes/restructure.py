"""RestructurePlan endpoints (PRD 3.8)."""
from decimal import Decimal, ROUND_HALF_UP, getcontext

from flask import Blueprint

from db import STORE
from errors import raise_err
from middleware import ALL_ROLES, auth, require_role
from response import ok_list, ok_object
from routes.loans import get_loan_or_404
from serialize import list_response, ser_plan
from services.core import (TERMINAL_LOAN_STATES, accrue_interest,
                           active_disaster_declaration, deferrals_of_loan,
                           margin_deficiency_check, notices_of_loan,
                           plans_of_loan, reevaluate_borrower, stamp_new,
                           touch)
from util import (add_months, as_bool, as_enum, as_int, as_pos_int, as_str,
                  body, need, new_id)

getcontext().prec = 60

bp = Blueprint("restructure", __name__)

PLAN_TYPES = ["STANDARD", "DISASTER"]
AMORT_STYLES = ["EQUAL_INSTALLMENT", "BALLOON"]
PLAN_TERMINAL = ("EXECUTED", "SUPERSEDED", "WITHDRAWN")
OPEN_PLAN_STATES = ("PROPOSED", "COMMITTEE_REVIEW", "APPROVED")


def get_plan_or_404(pid):
    p = STORE.plans.get(pid)
    if p is None:
        raise_err("ERR_NOT_FOUND", "Restructure plan not found")
    return p


def compute_installment(style, base_balance_cents, new_rate_bps, extension_months):
    """PRD 3.8: annuity (EQUAL_INSTALLMENT) or interest-only (BALLOON),
    rounded half-up to whole cents."""
    r = Decimal(new_rate_bps) / Decimal(1_200_000)
    base = Decimal(base_balance_cents)
    if style == "BALLOON":
        value = base * r
    else:
        if r == 0:
            value = base / Decimal(extension_months)
        else:
            factor = (1 + r) ** extension_months
            value = base * r * factor / (factor - 1)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def other_open_plan_exists(loan_id, except_plan_id):
    for p in plans_of_loan(loan_id):
        if p["id"] != except_plan_id and p["status"] not in PLAN_TERMINAL:
            return True
    return False


@bp.route("/restructure-plans", methods=["POST"])
def create_plan():
    uid, role = auth()
    require_role(role, ["LoanOfficer"])
    b = body()
    loan_account_id = as_str(need(b, "loan_account_id"), "loan_account_id")
    plan_type = as_enum(need(b, "plan_type"), "plan_type", PLAN_TYPES)
    style = as_enum(need(b, "amortization_style"), "amortization_style", AMORT_STYLES)
    extension_months = as_pos_int(need(b, "extension_months"), "extension_months")
    new_rate_bps = as_int(need(b, "new_rate_bps"), "new_rate_bps", min_value=0)
    capitalize = as_bool(need(b, "capitalize_interest"), "capitalize_interest")
    expected_loan_version = as_int(need(b, "expected_loan_version"), "expected_loan_version")
    loan = STORE.loans.get(loan_account_id)
    if loan is None:
        raise_err("ERR_NOT_FOUND", "Loan account not found")
    if expected_loan_version != loan["version"]:
        raise_err("ERR_STALE_VERSION", "expected_loan_version does not match the loan version")
    if loan["status"] != "ACTIVE":
        raise_err("ERR_LOAN_NOT_ACTIVE", "Restructure creation requires an ACTIVE loan")
    # Distress gate: posture DELINQUENT/DEFAULT or an ISSUED/ESCALATED margin call.
    gate_met = loan["payment_posture"] in ("DELINQUENT", "DEFAULT") or any(
        n["status"] in ("ISSUED", "ESCALATED") for n in notices_of_loan(loan["id"]))
    if not gate_met:
        raise_err("ERR_RESTRUCTURE_GATE_NOT_MET",
                  "No distress signal: posture and margin calls are clean")
    if plan_type == "DISASTER":
        borrower = STORE.borrowers.get(loan["borrower_id"])
        association = STORE.associations.get(loan["association_id"])
        declaration = None
        if borrower is not None and association is not None:
            declaration = active_disaster_declaration(association, borrower["county"])
        has_deferral = any(d["status"] in ("APPROVED", "IN_EFFECT", "EXPIRED")
                           for d in deferrals_of_loan(loan["id"]))
        if declaration is None or not has_deferral:
            raise_err("ERR_DISASTER_REQUIRED",
                      "DISASTER plan needs an active disaster declaration and a deferral")
    # Freeze economics: accrue to the clock first, then snapshot balances.
    accrue_interest(loan)
    base_balance = loan["outstanding_principal_cents"] + (
        loan["accrued_interest_cents"] if capitalize else 0)
    installment = compute_installment(style, base_balance, new_rate_bps,
                                      extension_months)
    # Supersede the prior non-terminal docket (PROPOSED/COMMITTEE_REVIEW/APPROVED).
    for p in plans_of_loan(loan["id"]):
        if p["status"] in OPEN_PLAN_STATES:
            p["status"] = "SUPERSEDED"
            touch(p)
    plan = stamp_new({
        "id": new_id(),
        "loan_account_id": loan["id"],
        "plan_type": plan_type,
        "amortization_style": style,
        "extension_months": extension_months,
        "new_rate_bps": new_rate_bps,
        "capitalize_interest": capitalize,
        "base_balance_cents": base_balance,
        "new_installment_cents": installment,
        "created_by_user_id": uid,
        "status": "PROPOSED",
    })
    STORE.plans[plan["id"]] = plan
    loan["status"] = "RESTRUCTURING"
    touch(loan)
    return ok_object(ser_plan(plan), code=201)


@bp.route("/restructure-plans/<pid>", methods=["GET"])
def get_plan(pid):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return ok_object(ser_plan(get_plan_or_404(pid)))


@bp.route("/restructure-plans", methods=["GET"])
def list_plans():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.plans.values(), ser_plan,
        [("loan_account_id", lambda e: e["loan_account_id"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.route("/restructure-plans/<pid>/submit", methods=["POST"])
def submit_plan(pid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    plan = get_plan_or_404(pid)
    if plan["status"] not in ("PROPOSED", "REJECTED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a PROPOSED or REJECTED plan can be submitted")
    was_rejected = plan["status"] == "REJECTED"
    plan["status"] = "COMMITTEE_REVIEW"
    touch(plan)
    if was_rejected:
        loan = get_loan_or_404(plan["loan_account_id"])
        if loan["status"] == "ACTIVE":
            loan["status"] = "RESTRUCTURING"
    return ok_object(ser_plan(plan))


@bp.route("/restructure-plans/<pid>/approve", methods=["POST"])
def approve_plan(pid):
    uid, role = auth()
    require_role(role, ["CreditCommittee"])
    plan = get_plan_or_404(pid)
    if plan["status"] != "COMMITTEE_REVIEW":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a plan in COMMITTEE_REVIEW can be approved")
    if uid == plan["created_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "The plan creator cannot approve this plan")
    plan["status"] = "APPROVED"
    touch(plan)
    return ok_object(ser_plan(plan))


@bp.route("/restructure-plans/<pid>/reject", methods=["POST"])
def reject_plan(pid):
    auth_uid, role = auth()
    require_role(role, ["CreditCommittee"])
    plan = get_plan_or_404(pid)
    if plan["status"] != "COMMITTEE_REVIEW":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a plan in COMMITTEE_REVIEW can be rejected")
    plan["status"] = "REJECTED"
    touch(plan)
    loan = get_loan_or_404(plan["loan_account_id"])
    if loan["status"] == "RESTRUCTURING" and not other_open_plan_exists(loan["id"], plan["id"]):
        loan["status"] = "ACTIVE"
    touch(loan)
    return ok_object(ser_plan(plan))


@bp.route("/restructure-plans/<pid>/execute", methods=["POST"])
def execute_plan(pid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    plan = get_plan_or_404(pid)
    if plan["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an APPROVED plan can be executed")
    loan = get_loan_or_404(plan["loan_account_id"])
    accrue_interest(loan)
    if plan["capitalize_interest"]:
        loan["outstanding_principal_cents"] = plan["base_balance_cents"]
        loan["accrued_interest_cents"] = 0
    loan["rate_bps"] = plan["new_rate_bps"]
    loan["maturity_date"] = add_months(loan["maturity_date"], plan["extension_months"])
    plan["status"] = "EXECUTED"
    touch(plan)
    if loan["status"] == "RESTRUCTURING":
        loan["status"] = "ACTIVE"
    loan["payment_posture"] = "CURRENT"
    loan["consecutive_delinquent_reviews"] = 0
    touch(loan)
    # Posture recompute is skipped once at execution (reset is authoritative);
    # margin deficiency and borrower standing still re-evaluate.
    margin_deficiency_check(loan)
    reevaluate_borrower(loan["borrower_id"])
    return ok_object(ser_plan(plan))


@bp.route("/restructure-plans/<pid>/withdraw", methods=["POST"])
def withdraw_plan(pid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    plan = get_plan_or_404(pid)
    if plan["status"] != "PROPOSED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a PROPOSED plan can be withdrawn")
    plan["status"] = "WITHDRAWN"
    touch(plan)
    loan = get_loan_or_404(plan["loan_account_id"])
    if loan["status"] == "RESTRUCTURING" and not other_open_plan_exists(loan["id"], plan["id"]):
        loan["status"] = "ACTIVE"
    touch(loan)
    return ok_object(ser_plan(plan))
