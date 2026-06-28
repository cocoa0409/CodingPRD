"""PolicyLoan endpoints (PRD §3.9), OCC-guarded on Policy.version (PRD §2.8)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from clock import get_now, parse_iso, format_iso_millis
from errors import err
from helpers import get_body, require_fields, serialize, paginate, sort_by_created
from middleware import get_identity, require_roles, require_owner_if_policyholder
from response import success
from services import policy_calc, ledger, timecalc

bp = Blueprint("policy_loans", __name__)


@bp.route("/policy-loans", methods=["POST"])
def disburse_loan():
    user_id, role = get_identity()
    require_roles(role, {"Policyholder", "PolicyAdmin"})
    body = get_body()
    require_fields(body, ["policy_id", "expected_policy_version", "principal_cents"])
    policy = db.policies.get(body["policy_id"])
    if policy is None:
        raise err("ERR_NOT_FOUND", "Policy not found")
    require_owner_if_policyholder(role, user_id, policy)

    principal = body["principal_cents"]
    if not isinstance(principal, int) or isinstance(principal, bool) or principal <= 0:
        raise err("ERR_VALIDATION", "principal_cents must be a positive integer")
    expected = body["expected_policy_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_VALIDATION", "expected_policy_version must be an integer")

    with db.LOCK:
        policy_calc.recompute_policy(policy)
        # OCC guard (PRD §2.8).
        if expected != policy["version"]:
            raise err("ERR_STALE_POLICY_VERSION", "Policy version is stale")

        plan = db.product_plans.get(policy["product_plan_id"])
        whole_years = timecalc.whole_years_between(parse_iso(policy["issue_date"]), get_now())
        if whole_years < plan["cash_value_vesting_years"]:
            raise err("ERR_CASH_VALUE_NOT_VESTED", "Cash value has not vested")

        # Loan cooldown vs prior SETTLED loans (PRD §3.9).
        for prior in db.policy_loans.values():
            if prior["policy_id"] != policy["id"] or prior["status"] != "SETTLED":
                continue
            settled = parse_iso(prior.get("settled_date"))
            if settled is None:
                continue
            cooldown_end = settled + timedelta(days=plan["loan_cooldown_days"])
            if get_now() < cooldown_end:
                raise err("ERR_LOAN_COOLDOWN_OVERLAP", "New loan inside cooldown window")

        # Fiscal cap: outstanding + new principal <= max_loan_to_cash_value_pct * net cash value.
        outstanding = policy_calc.outstanding_loan_balance_cents(policy["id"])
        net_cash = policy_calc.net_cash_value_cents(policy)
        cap = plan["max_loan_to_cash_value_pct"] * net_cash
        if outstanding + principal > cap:
            raise err("ERR_LOAN_EXCEEDS_CASH_VALUE", "Loan exceeds allowed cash value")

        loan = {
            "policy_id": policy["id"],
            "expected_policy_version": expected,
            "principal_cents": principal,
            "disbursed_date": format_iso_millis(get_now()),
            "settled_date": None,
            "accrued_interest_cents": 0,
            "repaid_principal_cents": 0,
            "status": "ACTIVE",
        }
        db.stamp_full(loan)
        db.policy_loans[loan["id"]] = loan
        # Disbursement bumps the policy version by one.
        db.touch(policy)
        policy_calc.recompute_policy(policy)
        ledger.append(policy["id"], "LOAN_DISBURSED", principal, policy["net_cash_value_cents"])
    return success(serialize(loan), status=201, response_type="object")


@bp.route("/policy-loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Policyholder", "ClaimsExaminer"})
    loan = db.policy_loans.get(loan_id)
    if loan is None:
        raise err("ERR_NOT_FOUND", "PolicyLoan not found")
    with db.LOCK:
        loan["accrued_interest_cents"] = policy_calc.accrued_interest_cents(loan)
    return success(serialize(loan), status=200, response_type="object")


@bp.route("/policy-loans", methods=["GET"])
def list_loans():
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Policyholder", "ClaimsExaminer"})
    items = list(db.policy_loans.values())
    policy_id = request.args.get("policy_id")
    status = request.args.get("status")
    if policy_id:
        items = [l for l in items if l["policy_id"] == policy_id]
    if status:
        items = [l for l in items if l["status"] == status]
    with db.LOCK:
        for l in items:
            l["accrued_interest_cents"] = policy_calc.accrued_interest_cents(l)
    items = sort_by_created(items)
    page, meta = paginate(items)
    return success([serialize(l) for l in page], status=200, response_type="array", pagination=meta)


@bp.route("/policy-loans/<loan_id>/repay", methods=["POST"])
def repay_loan(loan_id):
    user_id, role = get_identity()
    require_roles(role, {"Policyholder", "PolicyAdmin"})
    loan = db.policy_loans.get(loan_id)
    if loan is None:
        raise err("ERR_NOT_FOUND", "PolicyLoan not found")
    policy = db.policies.get(loan["policy_id"])
    require_owner_if_policyholder(role, user_id, policy)
    if loan["status"] not in ("ACTIVE", "CALLED"):
        raise err("ERR_INVALID_STATE", "Loan is not ACTIVE or CALLED")
    body = get_body()
    require_fields(body, ["amount_cents"])
    amount = body["amount_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise err("ERR_VALIDATION", "amount_cents must be a positive integer")

    with db.LOCK:
        outstanding_principal = loan["principal_cents"] - loan["repaid_principal_cents"]
        accrued = policy_calc.accrued_interest_cents(loan)
        required = outstanding_principal + accrued
        if amount < required:
            raise err("ERR_LOAN_UNDERPAID", "Repayment is less than outstanding principal plus interest")
        loan["status"] = "SETTLED"
        loan["settled_date"] = format_iso_millis(get_now())
        loan["repaid_principal_cents"] = loan["principal_cents"]
        loan["accrued_interest_cents"] = accrued
        db.touch(loan)
        if policy is not None:
            policy_calc.recompute_policy(policy)
            ledger.append(policy["id"], "LOAN_REPAID", outstanding_principal,
                          policy["net_cash_value_cents"])
            db.touch(policy)
    return success(serialize(loan), status=200, response_type="object")
