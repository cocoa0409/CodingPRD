"""Loan routes: create, read, list, payments, foreclosure."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, request

import db
import response
from errors import (
    ApiError,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_UNAUTHORIZED,
)
from middleware import require_auth
from services import calculations as calc
from services import transitions
from services.common import (
    bump,
    new_common_fields,
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    require_iso_datetime,
    require_str,
    require_enum,
    optional_iso_datetime,
    optional_int,
    optional_enum,
    sorted_by_created_at,
    strip_internal,
)
from services.lookup import (
    get_loan,
    get_fk_or_404,
    borrower_owns_loan,
)

bp = Blueprint("loans", __name__)


def _check_loan_ownership_for_borrower(loan: dict):
    if g.user_role == "Borrower" and not borrower_owns_loan(loan, g.user_id):
        raise ApiError(ERR_UNAUTHORIZED, "Borrower does not own this loan.")


def _serialize_loan(loan: dict) -> dict:
    return strip_internal(loan)


def _serialize_payment(p: dict) -> dict:
    return strip_internal(p)


def _serialize_case(c: dict) -> dict:
    return strip_internal(c)


# ---------- POST /loans ----------
@bp.post("/loans")
@require_auth(roles=["LoanServicer"])
def originate_loan():
    body = get_json_body()
    borrower_id = require_str(body, "borrower_id")
    origination_date = require_iso_datetime(body, "origination_date")
    original_principal_cents = require_int(body, "original_principal_cents")
    original_property_value_cents = require_int(body, "original_property_value_cents")
    interest_rate_bps = require_int(body, "interest_rate_bps")
    term_months = require_int(body, "term_months")
    pmi_monthly_cents = require_int(body, "pmi_monthly_cents")
    current_appraised_value = optional_int(body, "current_appraised_value_cents")

    # Body FK check
    get_fk_or_404(db.borrowers, borrower_id, name="Borrower")

    if original_principal_cents <= 0 or original_property_value_cents <= 0 or term_months <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "Numeric inputs must be positive.")
    if interest_rate_bps < 0 or pmi_monthly_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Numeric inputs must be non-negative.")

    with db.lock:
        loan = new_common_fields()
        loan["borrower_id"] = borrower_id
        loan["origination_date"] = db.fmt_ts(origination_date)
        loan["original_principal_cents"] = original_principal_cents
        loan["original_property_value_cents"] = original_property_value_cents
        loan["current_appraised_value_cents"] = current_appraised_value if current_appraised_value is not None else original_property_value_cents
        loan["interest_rate_bps"] = interest_rate_bps
        loan["term_months"] = term_months
        loan["pmi_monthly_cents"] = pmi_monthly_cents
        loan["scheduled_monthly_pi_cents"] = calc.amortization_schedule(
            original_principal_cents, interest_rate_bps, term_months
        )
        loan["principal_balance_cents"] = original_principal_cents
        loan["accrued_interest_cents"] = 0
        loan["escrow_monthly_cents"] = 0
        loan["outstanding_late_fees_cents"] = 0
        loan["next_due_date"] = db.fmt_ts(origination_date + timedelta(days=30))
        loan["status"] = "CURRENT"
        loan["max_dpd_observed_12mo"] = 0

        # PMI lifecycle
        ltv_bps = calc.compute_ltv_bps(loan, None)  # uses original_property_value baseline
        if ltv_bps >= calc.LTV_BORROWER_REQUEST_BPS:
            loan["pmi_required"] = True
            loan["pmi_status"] = "ACTIVE"
        else:
            loan["pmi_required"] = False
            loan["pmi_status"] = "NOT_APPLICABLE"

        transitions.recompute_total_monthly_payment(loan)
        loan["last_payment_posted_at"] = None
        loan["days_past_due"] = 0

        db.loans[loan["id"]] = loan

    return response.ok(_serialize_loan(loan), status=201)


# ---------- GET /loans/{id} ----------
@bp.get("/loans/<loan_id>")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def read_loan(loan_id: str):
    loan = get_loan(loan_id)
    _check_loan_ownership_for_borrower(loan)
    # Refresh derived fields on read
    transitions.refresh_dpd(loan)
    return response.ok(_serialize_loan(loan))


# ---------- GET /loans ----------
@bp.get("/loans")
@require_auth(roles=["LoanServicer", "ComplianceOfficer"])
def list_loans():
    limit, offset = parse_pagination()
    borrower_id = request.args.get("borrower_id")
    status = request.args.get("status")
    items = list(db.loans.values())
    if borrower_id is not None:
        items = [l for l in items if l.get("borrower_id") == borrower_id]
    if status is not None:
        items = [l for l in items if l.get("status") == status]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([_serialize_loan(x) for x in page], limit, offset, total)


# ---------- POST /loans/{id}/payments ----------
@bp.post("/loans/<loan_id>/payments")
@require_auth(roles=["LoanServicer", "Borrower"])
def post_payment(loan_id: str):
    loan = get_loan(loan_id)
    _check_loan_ownership_for_borrower(loan)
    body = get_json_body()

    amount_cents = require_int(body, "amount_cents")
    received_at = require_iso_datetime(body, "received_at")
    posting_strategy = optional_enum(
        body, "posting_strategy",
        {"STANDARD_WATERFALL", "PRINCIPAL_CURTAILMENT"},
        default="STANDARD_WATERFALL",
    )

    if amount_cents <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, "Payment amount must be > 0.")

    # State precondition: only post on certain statuses. The spec doesn't prohibit posting
    # in FORBEARANCE/FORECLOSURE explicitly except for transitions; we permit posting at any time
    # except PAID_OFF.
    if loan.get("status") == "PAID_OFF":
        raise ApiError(ERR_INVALID_STATE, "Loan is paid off; cannot post further payments.")

    with db.lock:
        # Find associated escrow account (1:1)
        ea = next((e for e in db.escrow_accounts.values() if e.get("loan_id") == loan_id), None)

        allocation = calc.post_payment(loan, ea, amount_cents, posting_strategy)

        # Determine payment status
        # Full installment satisfied = principal + interest + escrow + pmi covered enough to cure ≥1 installment
        scheduled_pi = loan.get("scheduled_monthly_pi_cents", 0)
        escrow_monthly = loan.get("escrow_monthly_cents", 0)
        pmi_monthly = loan.get("pmi_monthly_cents", 0) if loan.get("pmi_required") else 0
        one_installment = scheduled_pi + escrow_monthly + pmi_monthly
        installment_funds = (
            allocation["interest_cents"]
            + allocation["principal_cents"]
            + allocation["escrow_cents"]
            + allocation["pmi_cents"]
        )
        full_installment_covered = (one_installment > 0 and installment_funds >= one_installment)

        # Check for full payoff per PRD §3.2: "When the remittance is at
        # least the sum of principal_balance_cents, accrued_interest_cents,
        # and any outstanding fees — fully retiring the obligation — and the
        # loan was in CURRENT status, the loan transitions to PAID_OFF".
        # The check is made against the pre-allocation snapshot of the loan.
        payoff_target = (
            loan.get("principal_balance_cents", 0)
            + loan.get("accrued_interest_cents", 0)
            + loan.get("outstanding_late_fees_cents", 0)
        )
        was_current = loan.get("status") == "CURRENT"
        is_payoff = was_current and amount_cents >= payoff_target

        if is_payoff:
            # For a full payoff, force the allocation to zero principal and
            # let any surplus over the principal+interest+fees flow into the
            # escrow bucket (PRD §2.7 routes partial-cent remainders into
            # escrow; payoff surplus follows the same routing).
            old_principal = loan.get("principal_balance_cents", 0)
            old_interest = loan.get("accrued_interest_cents", 0)
            old_late = loan.get("outstanding_late_fees_cents", 0)
            allocation["principal_cents"] = old_principal
            allocation["interest_cents"] = old_interest
            allocation["late_fee_cents"] = old_late
            # Remaining funds after retiring obligation
            remaining = amount_cents - (old_principal + old_interest + old_late)
            # Apply remaining funds: escrow installment, then pmi, then suspense.
            escrow_monthly = loan.get("escrow_monthly_cents", 0)
            pmi_monthly = loan.get("pmi_monthly_cents", 0) if loan.get("pmi_required") else 0
            esc_take = min(remaining, escrow_monthly)
            allocation["escrow_cents"] = esc_take
            remaining -= esc_take
            pmi_take = min(remaining, pmi_monthly)
            allocation["pmi_cents"] = pmi_take
            remaining -= pmi_take
            allocation["suspense_cents"] = remaining

        # Apply allocation side effects
        transitions.apply_payment(loan, ea, allocation)

        # Recompute installment-covered after possible payoff allocation rewrite
        installment_funds = (
            allocation["interest_cents"]
            + allocation["principal_cents"]
            + allocation["escrow_cents"]
            + allocation["pmi_cents"]
        )
        full_installment_covered = (one_installment > 0 and installment_funds >= one_installment)

        payment_status = "POSTED" if (full_installment_covered or is_payoff) else "SUSPENSE"
        if not full_installment_covered and not is_payoff and allocation["suspense_cents"] == amount_cents:
            payment_status = "SUSPENSE"

        if is_payoff:
            transitions.transition_to_paid_off(loan)
            bump(loan)
        else:
            # Cascade DELINQUENT->CURRENT or REINSTATED->CURRENT if dpd cured
            transitions.post_payment_cascade_loan_status(loan)
            bump(loan)

        # Build Payment row (immutable: only id + created_at; no updated_at/version)
        created_ts = db.fmt_ts(db.utcnow())
        payment = {
            "id": db.new_id(),
            "created_at": created_ts,
            "loan_id": loan_id,
            "amount_cents": amount_cents,
            "received_at": db.fmt_ts(received_at),
            "posting_strategy": posting_strategy,
            "allocation": allocation,
            "status": payment_status,
            "posted_at": created_ts,
            "_seq": db.new_id()[:8],  # tie-breaker only
        }
        db.payments[payment["id"]] = payment

    return response.ok(_serialize_payment(payment), status=201)


# ---------- GET /loans/{id}/payments ----------
@bp.get("/loans/<loan_id>/payments")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def list_payments(loan_id: str):
    loan = get_loan(loan_id)
    _check_loan_ownership_for_borrower(loan)
    limit, offset = parse_pagination()
    items = [p for p in db.payments.values() if p.get("loan_id") == loan_id]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([strip_internal(x) for x in page], limit, offset, total)


# ---------- POST /loans/{id}/foreclosure ----------
@bp.post("/loans/<loan_id>/foreclosure")
@require_auth(roles=["LoanServicer"])
def file_foreclosure(loan_id: str):
    loan = get_loan(loan_id)
    body = get_json_body()
    expected_loan_version = require_int(body, "expected_loan_version")

    # State precondition: loan must be DELINQUENT and >= 120 days past due, no ACTIVE forbearance
    transitions.refresh_dpd(loan)
    if loan.get("status") != "DELINQUENT":
        raise ApiError(ERR_INVALID_STATE, "Loan must be DELINQUENT to file foreclosure.")
    if loan.get("days_past_due", 0) < calc.FORECLOSURE_THRESHOLD_DAYS:
        raise ApiError(ERR_INVALID_STATE, "Loan does not meet foreclosure threshold.")
    has_active_forb = any(
        p for p in db.forbearance_plans.values()
        if p.get("loan_id") == loan_id and p.get("status") == "ACTIVE"
    )
    if has_active_forb:
        raise ApiError(ERR_INVALID_STATE, "Loan has an active forbearance plan.")

    # OCC check (priority 6, after state per validation table)
    if expected_loan_version != loan.get("version"):
        raise ApiError(ERR_STALE_VERSION, "expected_loan_version does not match.")

    with db.lock:
        case = new_common_fields()
        case["loan_id"] = loan_id
        case["initiated_at"] = db.fmt_ts(db.utcnow())
        case["status"] = "FILED"
        case["sale_date"] = None
        case["cure_amount_cents"] = calc.foreclosure_cure_amount(loan)
        db.foreclosure_cases[case["id"]] = case

        # Auto-transition FILED -> MEDIATION_REQUIRED (HAMP-style mandatory mediation)
        case["status"] = "MEDIATION_REQUIRED"
        bump(case)
        transitions.refresh_cure_amount(case)

        # Loan cascade: status -> FORECLOSURE
        loan["status"] = "FORECLOSURE"
        bump(loan)

    return response.ok(_serialize_case(case), status=201)


# ---------- GET /loans/{id}/foreclosure-cases ----------
@bp.get("/loans/<loan_id>/foreclosure-cases")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def list_foreclosure_cases(loan_id: str):
    loan = get_loan(loan_id)
    _check_loan_ownership_for_borrower(loan)
    limit, offset = parse_pagination()
    items = [c for c in db.foreclosure_cases.values() if c.get("loan_id") == loan_id]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([_serialize_case(x) for x in page], limit, offset, total)
