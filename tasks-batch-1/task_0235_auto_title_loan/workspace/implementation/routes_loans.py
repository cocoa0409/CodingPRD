"""Loan servicing routes (PRD 3.4-3.8)."""
from flask import Blueprint, request

import db
import lookups
import calculations as calc
import device_service
import loan_service
from clock import get_now
from errors import err
from middleware import authenticate, require_role
from response import success, list_success
from serialize import public
from timeutil import iso_now, parse_iso
from validate import get_body, require_str, require_int, parse_pagination, paginate

bp = Blueprint("loans", __name__)


def _sorted_public(entities):
    rows = sorted(entities, key=lambda e: e["_seq"])
    return [public(e) for e in rows]


def _past_due_arrears(loan):
    """Sum past-due principal and interest over PAST_DUE installments."""
    arrears_principal = 0
    arrears_interest = 0
    for inst in lookups.installments_for_loan(loan["id"]):
        if inst["status"] == "PAST_DUE":
            arrears_principal += inst["principal_due_cents"]
            arrears_interest += inst["interest_due_cents"]
    return arrears_principal, arrears_interest


# ---------------------------------------------------------------------------
# Loan reads
# ---------------------------------------------------------------------------
@bp.route("/atl/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    _, role = authenticate()
    require_role(role, {"Underwriter", "ComplianceAdmin", "LoanServicer", "RecoveryManager", "TitleClerk"})
    loan = lookups.get_or_404(db.loans, loan_id)
    return success(public(loan), status=200)


@bp.route("/atl/loans", methods=["GET"])
def list_loans():
    _, role = authenticate()
    require_role(role, {"Underwriter", "ComplianceAdmin", "LoanServicer", "RecoveryManager", "TitleClerk"})
    limit, offset = parse_pagination()
    rows = list(db.loans.values())
    application_id = request.args.get("application_id")
    borrower_id = request.args.get("borrower_id")
    vehicle_id = request.args.get("vehicle_id")
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    if borrower_id is not None:
        rows = [r for r in rows if r["borrower_id"] == borrower_id]
    if vehicle_id is not None:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    items = _sorted_public(rows)
    return list_success(paginate(items, limit, offset), limit, offset, len(items))


@bp.route("/atl/loans/<loan_id>/installments", methods=["GET"])
def list_installments(loan_id):
    _, role = authenticate()
    require_role(role, {"Underwriter", "ComplianceAdmin", "LoanServicer"})
    lookups.get_or_404(db.loans, loan_id)
    limit, offset = parse_pagination()
    rows = [i for i in db.installments.values() if i["loan_id"] == loan_id]
    items = _sorted_public(rows)
    return list_success(paginate(items, limit, offset), limit, offset, len(items))


@bp.route("/atl/loans/<loan_id>/payoff-quote", methods=["GET"])
def payoff_quote(loan_id):
    _, role = authenticate()
    require_role(role, {"LoanServicer", "Underwriter", "ComplianceAdmin"})
    loan = lookups.get_or_404(db.loans, loan_id)

    has_active_repo = lookups.active_repo_for_loan(loan_id) is not None
    redemption = calc.redemption_amount(
        loan["principal_balance_cents"], loan["accrued_interest_cents"],
        loan["fees_balance_cents"], has_active_repo)

    arrears_principal, arrears_interest = _past_due_arrears(loan)
    is_default = loan["delinquency_status"] == "DEFAULT"
    reinstatement = calc.reinstatement_amount(
        arrears_principal, arrears_interest, loan["fees_balance_cents"], is_default)

    return success({
        "redemption_amount_cents": redemption,
        "reinstatement_amount_cents": reinstatement,
    }, status=200)


# ---------------------------------------------------------------------------
# Assess delinquency (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.route("/atl/loans/<loan_id>/assess-delinquency", methods=["POST"])
def assess_delinquency(loan_id):
    _, role = authenticate()
    require_role(role, {"LoanServicer"})
    loan = lookups.get_or_404(db.loans, loan_id)

    now = get_now()

    # State preconditions (PRD 3.6): CURRENT, OUTSTANDING, at least one
    # SCHEDULED installment past due -> else ERR_INVALID_STATE.
    if loan["delinquency_status"] != "CURRENT" or loan["payoff_status"] != "OUTSTANDING":
        raise err("ERR_INVALID_STATE", "loan not assessable")

    newly_past_due = [
        inst for inst in lookups.installments_for_loan(loan_id)
        if inst["status"] == "SCHEDULED" and parse_iso(inst["due_date"]) < now
    ]
    if not newly_past_due:
        raise err("ERR_INVALID_STATE", "nothing past due to assess")

    accrued_add = 0
    fees_add = 0
    for inst in newly_past_due:
        inst["status"] = "PAST_DUE"
        accrued_add += inst["interest_due_cents"]
        fee = calc.late_fee_for_installment(inst["principal_due_cents"])
        inst["late_fee_cents"] = fee
        fees_add += fee
        db.touch(inst)

    loan["accrued_interest_cents"] += accrued_add
    loan["fees_balance_cents"] += fees_add
    loan["delinquency_status"] = "DELINQUENT"

    # Cascade: issue STARTER_DISABLE on the vehicle's device if one exists.
    device = lookups.device_for_vehicle(loan["vehicle_id"])
    device_service.cascade_starter_disable(device)

    db.touch(loan)
    return success(public(loan), status=200)


# ---------------------------------------------------------------------------
# Declare default (PRD 3.7) — creates a repossession order (depth-3 cascade)
# ---------------------------------------------------------------------------
@bp.route("/atl/loans/<loan_id>/declare-default", methods=["POST"])
def declare_default(loan_id):
    _, role = authenticate()
    require_role(role, {"LoanServicer"})
    loan = lookups.get_or_404(db.loans, loan_id)

    if loan["delinquency_status"] != "DELINQUENT" or loan["payoff_status"] != "OUTSTANDING":
        raise err("ERR_INVALID_STATE", "loan not in DELINQUENT/OUTSTANDING")

    loan["delinquency_status"] = "DEFAULT"

    # Cascade: create RepossessionOrder (ORDERED) which itself issues a
    # STARTER_DISABLE command to the vehicle's device (depth-3 chain).
    order = db.common_fields(with_version=True)
    order.update({
        "loan_id": loan["id"],
        "vehicle_id": loan["vehicle_id"],
        "recovered_at": None,
        "redemption_deadline": None,
        "sale_proceeds_cents": None,
        "deficiency_cents": None,
        "status": "ORDERED",
    })
    db.repossession_orders[order["id"]] = order

    device = lookups.device_for_vehicle(loan["vehicle_id"])
    device_service.cascade_starter_disable(device)

    db.touch(loan)
    return success(public(loan), status=200)


# ---------------------------------------------------------------------------
# Payments (PRD 3.6, 3.7)
# ---------------------------------------------------------------------------
PAYMENT_TYPES = {"REGULAR", "REINSTATEMENT", "REDEMPTION"}


def _record_payment(loan, amount, payment_type, alloc):
    payment = db.common_fields(with_version=True)
    payment.update({
        "loan_id": loan["id"],
        "amount_cents": amount,
        "payment_type": payment_type,
        "posted_at": iso_now(get_now()),
        "principal_applied_cents": alloc["principal_applied_cents"],
        "interest_applied_cents": alloc["interest_applied_cents"],
        "fees_applied_cents": alloc["fees_applied_cents"],
        "overpayment_cents": alloc["overpayment_cents"],
    })
    db.payments[payment["id"]] = payment
    return payment


@bp.route("/atl/loans/<loan_id>/payments", methods=["POST"])
def post_payment(loan_id):
    _, role = authenticate()
    require_role(role, {"LoanServicer"})
    loan = lookups.get_or_404(db.loans, loan_id)
    body = get_body()

    amount = require_int(body, "amount_cents")
    payment_type = require_str(body, "payment_type")
    if payment_type not in PAYMENT_TYPES:
        raise err("ERR_INVALID_REQUEST", "payment_type must be one of %s" % sorted(PAYMENT_TYPES))

    if amount <= 0:
        raise err("ERR_VALIDATION_RANGE", "amount_cents must be > 0")

    if payment_type == "REGULAR":
        return _post_regular(loan, amount)
    if payment_type == "REINSTATEMENT":
        return _post_reinstatement(loan, amount)
    return _post_redemption(loan, amount)


def _post_regular(loan, amount):
    """REGULAR waterfall (PRD 3.6); may trigger OUTSTANDING -> PAID_OFF (PRD 3.7)."""
    alloc = calc.payment_allocation(
        amount, loan["fees_balance_cents"], loan["accrued_interest_cents"],
        loan["principal_balance_cents"])

    loan["fees_balance_cents"] -= alloc["fees_applied_cents"]
    loan["accrued_interest_cents"] -= alloc["interest_applied_cents"]
    loan["principal_balance_cents"] -= alloc["principal_applied_cents"]
    db.touch(loan)

    payment = _record_payment(loan, amount, "REGULAR", alloc)

    # Payoff transition (PRD 3.7) bumps the loan version again via maybe_payoff.
    loan_service.maybe_payoff(loan)

    return success(public(payment), status=201)


def _post_reinstatement(loan, amount):
    """REINSTATEMENT cure (PRD 3.7) — DELINQUENT or DEFAULT -> CURRENT."""
    if loan["delinquency_status"] not in ("DELINQUENT", "DEFAULT"):
        raise err("ERR_INVALID_STATE", "loan not curable by reinstatement")

    arrears_principal, arrears_interest = _past_due_arrears(loan)
    is_default = loan["delinquency_status"] == "DEFAULT"
    required = calc.reinstatement_amount(
        arrears_principal, arrears_interest, loan["fees_balance_cents"], is_default)

    if amount < required:
        raise err("ERR_INSUFFICIENT_PAYMENT", "payment does not cover reinstatement amount")

    # Ledger updates (PRD 3.7): the cure exactly retires arrears+fees(+repo).
    loan["principal_balance_cents"] -= arrears_principal
    loan["accrued_interest_cents"] -= arrears_interest
    loan["fees_balance_cents"] = 0

    # All PAST_DUE installments -> PAID.
    for inst in lookups.installments_for_loan(loan["id"]):
        if inst["status"] == "PAST_DUE":
            inst["status"] = "PAID"
            db.touch(inst)

    device = lookups.device_for_vehicle(loan["vehicle_id"])

    if is_default:
        # DEFAULT cure: cancel active repo, reset disable count to 0.
        loan_service.cancel_active_repo_cascade(loan)
        device_service.cascade_starter_enable(device, reset_to_zero=True)
    else:
        # DELINQUENT cure: decrement disable count (floor 0).
        device_service.cascade_starter_enable(device, reset_to_zero=False)

    loan["delinquency_status"] = "CURRENT"
    db.touch(loan)

    # Allocation fields on the payment record: the cure retires fees+interest+
    # principal arrears; record those as the applied portions, remainder as
    # overpayment (exact integer cents).
    alloc = _reinstatement_alloc(amount, arrears_principal, arrears_interest, required)
    payment = _record_payment(loan, amount, "REINSTATEMENT", alloc)
    return success(public(payment), status=201)


def _reinstatement_alloc(amount, arrears_principal, arrears_interest, required):
    """Applied portions for a reinstatement payment record (PRD 3.6 field set).

    fees_applied = whatever portion of `required` is fees+repo (required minus
    arrears principal/interest); principal/interest applied = arrears; the
    surplus beyond `required` is overpayment.
    """
    fees_applied = required - arrears_principal - arrears_interest
    overpayment = amount - required
    return {
        "principal_applied_cents": arrears_principal,
        "interest_applied_cents": arrears_interest,
        "fees_applied_cents": fees_applied,
        "overpayment_cents": overpayment,
    }


def _post_redemption(loan, amount):
    """REDEMPTION full payoff (PRD 3.7) — OUTSTANDING -> REDEEMED."""
    if loan["payoff_status"] != "OUTSTANDING":
        raise err("ERR_INVALID_STATE", "loan not in OUTSTANDING")

    has_active_repo = lookups.active_repo_for_loan(loan["id"]) is not None
    required = calc.redemption_amount(
        loan["principal_balance_cents"], loan["accrued_interest_cents"],
        loan["fees_balance_cents"], has_active_repo)

    if amount < required:
        raise err("ERR_INSUFFICIENT_PAYMENT", "payment does not cover redemption amount")

    principal_applied = loan["principal_balance_cents"]
    interest_applied = loan["accrued_interest_cents"]
    fees_component = loan["fees_balance_cents"]
    repo_component = required - principal_applied - interest_applied - fees_component
    fees_applied = fees_component + repo_component  # fees + repo recovery
    overpayment = amount - required

    loan["principal_balance_cents"] = 0
    loan["accrued_interest_cents"] = 0
    loan["fees_balance_cents"] = 0
    loan["payoff_status"] = "REDEEMED"

    # Cascades (PRD 3.7): lien release -> vehicle CLEAR; cancel active repo;
    # STARTER_ENABLE reset to 0.
    loan_service.release_lien_cascade(loan)
    loan_service.cancel_active_repo_cascade(loan)
    device = lookups.device_for_vehicle(loan["vehicle_id"])
    device_service.cascade_starter_enable(device, reset_to_zero=True)

    db.touch(loan)

    alloc = {
        "principal_applied_cents": principal_applied,
        "interest_applied_cents": interest_applied,
        "fees_applied_cents": fees_applied,
        "overpayment_cents": overpayment,
    }
    payment = _record_payment(loan, amount, "REDEMPTION", alloc)
    return success(public(payment), status=201)


@bp.route("/atl/loans/<loan_id>/payments", methods=["GET"])
def list_payments(loan_id):
    _, role = authenticate()
    require_role(role, {"LoanServicer", "ComplianceAdmin", "Underwriter"})
    lookups.get_or_404(db.loans, loan_id)
    limit, offset = parse_pagination()
    rows = [p for p in db.payments.values() if p["loan_id"] == loan_id]
    items = _sorted_public(rows)
    return list_success(paginate(items, limit, offset), limit, offset, len(items))


# ---------------------------------------------------------------------------
# Renewals (PRD 3.8) — OCC-guarded
# ---------------------------------------------------------------------------
@bp.route("/atl/loans/<loan_id>/renewals", methods=["POST"])
def create_renewal(loan_id):
    _, role = authenticate()
    require_role(role, {"LoanServicer"})
    loan = lookups.get_or_404(db.loans, loan_id)
    body = get_body()

    expected_loan_version = require_int(body, "expected_loan_version")
    new_term_months = require_int(body, "new_term_months")

    if new_term_months < 1:
        raise err("ERR_VALIDATION_RANGE", "new_term_months must be >= 1")

    # Guarded order (PRD 3.8): (1) renewable state, (2) OCC, (3) rollover limit.
    if loan["payoff_status"] != "OUTSTANDING":
        raise err("ERR_INVALID_STATE", "loan not in OUTSTANDING; cannot renew")

    if expected_loan_version != loan["version"]:
        raise err("ERR_STALE_LOAN_VERSION", "expected_loan_version does not match current loan version")

    borrower = db.borrowers.get(loan["borrower_id"])
    prof = lookups.borrower_regulatory_profile(borrower) if borrower else None
    if prof is None:
        raise err("ERR_INVALID_STATE", "no regulatory profile for borrower state")
    if loan["renewal_count"] >= prof["max_renewals"]:
        raise err("ERR_RENEWAL_LIMIT_REACHED", "rollover limit reached")

    rolled_fees, new_principal = calc.renewal_capitalization(
        loan["principal_balance_cents"], loan["accrued_interest_cents"],
        loan["fees_balance_cents"])

    loan["principal_balance_cents"] = new_principal
    loan["accrued_interest_cents"] = 0
    loan["fees_balance_cents"] = 0
    loan["term_months"] = new_term_months
    loan["renewal_count"] += 1
    db.touch(loan)

    renewal = db.common_fields(with_version=True)
    renewal.update({
        "loan_id": loan["id"],
        "expected_loan_version": expected_loan_version,
        "new_term_months": new_term_months,
        "rolled_fees_cents": rolled_fees,
        "new_principal_cents": new_principal,
        "renewal_index": loan["renewal_count"],
    })
    db.renewals[renewal["id"]] = renewal
    return success(public(renewal), status=201)


@bp.route("/atl/loans/<loan_id>/renewals", methods=["GET"])
def list_renewals(loan_id):
    _, role = authenticate()
    require_role(role, {"LoanServicer", "ComplianceAdmin"})
    lookups.get_or_404(db.loans, loan_id)
    limit, offset = parse_pagination()
    rows = [r for r in db.renewals.values() if r["loan_id"] == loan_id]
    items = _sorted_public(rows)
    return list_success(paginate(items, limit, offset), limit, offset, len(items))
