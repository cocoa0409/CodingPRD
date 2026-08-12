"""PolicyLoan endpoints: origination, accrual, repayment, reads (PRD §3.6)."""
from flask import Blueprint

import domain
import errors
from db import store
from middleware import require_auth, parse_pagination, json_body, require_int, ALL_ROLES
from response import ok_object, ok_list
from routes.policies import get_policy_or_404, check_policyholder_ownership, _paged
from services import calculations as calc
from services import engine
from util import parse_date

bp = Blueprint("loans", __name__)


def get_loan_or_404(policy, loan_id):
    loan = store.loans.get(loan_id)
    if loan is None or loan["policy_id"] != policy["id"]:
        raise errors.not_found(errors.ERR_LOAN_NOT_FOUND, "policy loan")
    return loan


@bp.route("/policies/<policy_id>/loans", methods=["POST"])
def originate_loan(policy_id):
    ctx = require_auth(["Policyholder"])
    policy = get_policy_or_404(policy_id)
    if policy["form_status"] in domain.POLICY_FORM_TERMINAL:
        raise errors.already_terminal("Policy is in a terminal form state")
    if policy["form_status"] != "IN_FORCE":
        raise errors.invalid_state("Loans require form_status IN_FORCE")
    if policy["premium_payment_status"] not in ("CURRENT", "GRACE"):
        raise errors.invalid_state("Loans require premium_payment_status CURRENT or GRACE")
    check_policyholder_ownership(ctx, policy)
    body = json_body(required=True)
    amount = require_int(body, "requested_amount_cents")
    if amount <= 0:
        raise errors.invalid_request("requested_amount_cents must be positive")
    # Loan availability (priority 10): net of outstanding principal + interest
    available = (policy["cash_value_cents"]
                 - policy["outstanding_loan_principal_cents"]
                 - policy["accrued_loan_interest_cents"])
    if amount > available:
        raise errors.insufficient_cash_value(
            "Requested loan exceeds available cash value")

    today = store.current_date()
    loan = domain.stamp_new({
        "policy_id": policy["id"],
        "requested_amount_cents": amount,
        "origination_date": today,
        "annual_interest_rate_bps": domain.LOAN_ANNUAL_INTEREST_RATE_BPS,
        "outstanding_principal_cents": amount,
        "accrued_interest_cents": 0,
        "last_accrual_date": today,
        "status": "ACTIVE",
    })
    store.loans[loan["id"]] = loan
    policy["outstanding_loan_principal_cents"] += amount
    engine.post_ledger(policy, domain.ENTRY_LOAN_DISBURSEMENT, -amount)
    domain.touch_policy(policy)
    return ok_object(domain.serialize_loan(loan), status=201)


@bp.route("/policies/<policy_id>/loans", methods=["GET"])
def list_loans(policy_id):
    require_auth(ALL_ROLES)
    policy = get_policy_or_404(policy_id)
    return _paged([l for l in store.loans.values() if l["policy_id"] == policy["id"]],
                  domain.serialize_loan)


@bp.route("/policies/<policy_id>/loans/<loan_id>", methods=["GET"])
def get_loan(policy_id, loan_id):
    require_auth(ALL_ROLES)
    policy = get_policy_or_404(policy_id)
    return ok_object(domain.serialize_loan(get_loan_or_404(policy, loan_id)))


@bp.route("/policies/<policy_id>/loans/<loan_id>/accrue-interest", methods=["POST"])
def accrue_interest(policy_id, loan_id):
    require_auth(["PlatformAdmin"])
    policy = get_policy_or_404(policy_id)
    loan = get_loan_or_404(policy, loan_id)
    body = json_body()
    as_of = store.current_date()
    if body.get("as_of_date") is not None:
        as_of = parse_date(body["as_of_date"])
        if as_of is None:
            # also accept full ISO datetimes; take the date part
            from util import parse_datetime
            dt = parse_datetime(body["as_of_date"])
            if dt is None:
                raise errors.invalid_request("as_of_date must be an ISO date")
            as_of = dt.date()
    if loan["status"] in domain.LOAN_TERMINAL:
        raise errors.already_terminal("Loan is in a terminal state")
    template = domain.template_of(policy)
    if as_of > loan["last_accrual_date"]:
        calc.accrue_loan(loan, policy, template, as_of)
    return ok_object(domain.serialize_loan(loan))


@bp.route("/policies/<policy_id>/loans/<loan_id>/repayments", methods=["POST"])
def repay_loan(policy_id, loan_id):
    ctx = require_auth(["Policyholder"])
    policy = get_policy_or_404(policy_id)
    loan = get_loan_or_404(policy, loan_id)
    if loan["status"] in domain.LOAN_TERMINAL:
        raise errors.already_terminal("Loan is in a terminal state")
    check_policyholder_ownership(ctx, policy)
    body = json_body(required=True)
    amount = require_int(body, "amount_cents", minimum=1)

    # Waterfall: accrue interest to today, then interest first, then principal
    template = domain.template_of(policy)
    calc.accrue_loan(loan, policy, template, store.current_date())

    remaining = amount
    pay_interest = min(remaining, loan["accrued_interest_cents"])
    loan["accrued_interest_cents"] -= pay_interest
    policy["accrued_loan_interest_cents"] -= pay_interest
    remaining -= pay_interest
    pay_principal = min(remaining, loan["outstanding_principal_cents"])
    loan["outstanding_principal_cents"] -= pay_principal
    policy["outstanding_loan_principal_cents"] -= pay_principal
    remaining -= pay_principal

    if loan["outstanding_principal_cents"] == 0 and loan["accrued_interest_cents"] == 0:
        loan["status"] = "REPAID"
    domain.touch(loan)
    engine.post_ledger(policy, domain.ENTRY_LOAN_REPAYMENT_CREDIT, amount)
    domain.touch_policy(policy)
    return ok_object(domain.serialize_loan(loan))


@bp.route("/policies/<policy_id>/loans/<loan_id>/accruals", methods=["GET"])
def list_loan_accruals(policy_id, loan_id):
    require_auth(ALL_ROLES)
    policy = get_policy_or_404(policy_id)
    loan = get_loan_or_404(policy, loan_id)
    rows = [a for a in store.loan_accruals.values() if a["loan_id"] == loan["id"]]
    return _paged(rows, domain.serialize_accrual)


# ---------------------------------------------------------------------------
# Flat filtered listings (reverse reachability)
# ---------------------------------------------------------------------------
@bp.route("/policy-loans", methods=["GET"])
def list_all_loans():
    require_auth(ALL_ROLES)
    records = list(store.loans.values())
    policy_id = __import__("flask").request.args.get("policy_id")
    if policy_id is not None:
        records = [l for l in records if l["policy_id"] == policy_id]
    return _paged(records, domain.serialize_loan)


@bp.route("/policy-loans/<loan_id>", methods=["GET"])
def get_loan_flat(loan_id):
    require_auth(ALL_ROLES)
    loan = store.loans.get(loan_id)
    if loan is None:
        raise errors.not_found(errors.ERR_LOAN_NOT_FOUND, "policy loan")
    return ok_object(domain.serialize_loan(loan))


@bp.route("/loan-interest-accruals", methods=["GET"])
def list_all_accruals():
    require_auth(ALL_ROLES)
    records = list(store.loan_accruals.values())
    loan_id = __import__("flask").request.args.get("loan_id")
    if loan_id is not None:
        records = [a for a in records if a["loan_id"] == loan_id]
    return _paged(records, domain.serialize_accrual)


@bp.route("/loan-interest-accruals/<row_id>", methods=["GET"])
def get_accrual_flat(row_id):
    require_auth(ALL_ROLES)
    row = store.loan_accruals.get(row_id)
    if row is None:
        raise errors.not_found(errors.ERR_NOT_FOUND, "loan interest accrual")
    return ok_object(domain.serialize_accrual(row))
