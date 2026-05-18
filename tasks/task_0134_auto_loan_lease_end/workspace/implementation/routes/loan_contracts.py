"""Loan contract endpoints — PRD §3.3, §3.6, §3.8."""
from __future__ import annotations

from flask import Blueprint, g, request

from config import (
    LOAN_TERMS,
    ROLE_COLLECTIONS_AGENT,
    ROLE_CUSTOMER,
    ROLE_FINANCE_MANAGER,
    ROLE_LOAN_OFFICER,
    TIER_5_DECLINED,
)
from db import store
from errors import (
    err_contract_not_activatable,
    err_contract_not_found,
    err_customer_not_active,
    err_customer_not_found,
    err_down_payment_below_minimum,
    err_invalid_request,
    err_loan_not_defaulted,
    err_loan_not_pending_approval,
    err_loan_tier_declined,
    err_reinstate_has_outstanding_defaults,
    err_vehicle_not_available,
    err_vehicle_not_found,
)
from middleware import is_customer, require_auth
from response import success
from routes._helpers import (
    check_version,
    get_json,
    parse_version,
)
from services.calculations import (
    loan_monthly_payment_cents,
    loan_payoff_book_cents,
    loan_payoff_cash_cents,
    minimum_down_payment_loan_cents,
    tier_apr_bps,
)
from services.engine import (
    cascade_auto_cancel_gap_riders_for_contract,
    generate_payment_schedule,
    get_customer_or_404,
    get_loan_contract_or_404,
    stamp_create,
    stamp_update,
)
from services.serializers import serialize_loan_contract

bp = Blueprint("loan_contracts", __name__)


def _check_customer_ownership(customer_id: str):
    if is_customer() and g.user_id != customer_id:
        raise err_customer_not_found()


# ── POST /customers/{customerId}/loan-contracts ────────────────────────────


@bp.post("/customers/<customer_id>/loan-contracts")
@require_auth([ROLE_LOAN_OFFICER])
def create_loan(customer_id):
    customer = get_customer_or_404(customer_id)
    body = get_json()
    vehicle_id = body.get("vehicle_id")
    if not isinstance(vehicle_id, str) or not vehicle_id:
        raise err_invalid_request("vehicle_id is required.")
    veh = store.vehicles.get(vehicle_id)
    if veh is None:
        raise err_vehicle_not_found()

    down_payment = body.get("down_payment_cents")
    if down_payment is None or isinstance(down_payment, bool) or not isinstance(down_payment, int):
        raise err_invalid_request("down_payment_cents must be an integer.")
    if down_payment < 0:
        raise err_invalid_request("down_payment_cents must be >= 0.")
    if down_payment > veh["msrp_cents"]:
        raise err_invalid_request("down_payment_cents must not exceed msrp_cents.")

    term_months = body.get("term_months")
    if term_months is None or isinstance(term_months, bool) or not isinstance(term_months, int):
        raise err_invalid_request("term_months must be an integer.")
    if term_months not in LOAN_TERMS:
        raise err_invalid_request(
            f"term_months must be one of {list(LOAN_TERMS)}."
        )

    with store.lock:
        lc = {
            "customer_id": customer_id,
            "vehicle_id": vehicle_id,
            "principal_cents": veh["msrp_cents"] - down_payment,
            "down_payment_cents": down_payment,
            "term_months": term_months,
            "apr_bps": None,
            "base_apr_bps": None,
            "monthly_payment_cents": None,
            "remaining_principal_cents": None,
            "total_principal_paid_cents": 0,
            "total_interest_paid_cents": 0,
            "payments_made_count": 0,
            "payments_scheduled_count": None,
            "status": "PENDING_APPROVAL",
            "origination_day_index": None,
        }
        stamp_create(lc)
        store.loan_contracts[lc["id"]] = lc
    return success(serialize_loan_contract(lc), 201)


# ── POST /customers/{customerId}/loan-contracts/{contractId}/approve ───────


@bp.post("/customers/<customer_id>/loan-contracts/<contract_id>/approve")
@require_auth([ROLE_LOAN_OFFICER])
def approve_loan(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    lc = get_loan_contract_or_404(customer_id, contract_id)
    body = get_json()
    expected = parse_version(body)

    # Priority 4: state check (PRD §2.11: precedes OCC at priority 12).
    if lc["status"] != "PENDING_APPROVAL":
        raise err_loan_not_pending_approval(
            f"Loan is in {lc['status']}; approval requires PENDING_APPROVAL."
        )
    # Customer must be ACTIVE.
    if customer["status"] != "ACTIVE":
        raise err_customer_not_active()
    # Tier check: TIER_5_DECLINED is rejected.
    if customer["fico_tier"] == TIER_5_DECLINED:
        raise err_loan_tier_declined()
    # Down payment check (uses LOAN minimum schedule).
    veh = store.vehicles.get(lc["vehicle_id"])
    if veh is None:
        raise err_vehicle_not_found()
    min_dp = minimum_down_payment_loan_cents(veh["msrp_cents"], customer["fico_tier"])
    if lc["down_payment_cents"] < min_dp:
        raise err_down_payment_below_minimum(
            f"down_payment_cents={lc['down_payment_cents']} below minimum {min_dp} for {customer['fico_tier']}."
        )
    # Vehicle must be AVAILABLE.
    if veh["status"] != "AVAILABLE":
        raise err_vehicle_not_available()
    # Priority 12: OCC version check (PRD §2.11: last).
    check_version(lc, expected)

    with store.lock:
        # Vehicle → SOLD.
        veh["status"] = "SOLD"
        stamp_update(veh)
        # APR from tier.
        apr = tier_apr_bps(customer["fico_tier"])
        lc["base_apr_bps"] = apr
        lc["apr_bps"] = apr
        # Monthly payment.
        lc["monthly_payment_cents"] = loan_monthly_payment_cents(
            principal_cents=lc["principal_cents"],
            apr_bps=apr,
            term_months=lc["term_months"],
        )
        lc["remaining_principal_cents"] = lc["principal_cents"]
        lc["payments_scheduled_count"] = lc["term_months"]
        lc["origination_day_index"] = customer["clock_day_index"]
        lc["status"] = "APPROVED"
        stamp_update(lc)
    return success(serialize_loan_contract(lc))


# ── POST /customers/{customerId}/loan-contracts/{contractId}/activate ──────


@bp.post("/customers/<customer_id>/loan-contracts/<contract_id>/activate")
@require_auth([ROLE_LOAN_OFFICER])
def activate_loan(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    lc = get_loan_contract_or_404(customer_id, contract_id)
    body = get_json()
    expected = parse_version(body)
    check_version(lc, expected)

    if lc["status"] != "APPROVED":
        raise err_contract_not_activatable(
            f"Loan is in {lc['status']}; activation requires APPROVED."
        )

    with store.lock:
        lc["status"] = "ACTIVE"
        stamp_update(lc)
        generate_payment_schedule(lc, contract_type="LOAN")
    return success(serialize_loan_contract(lc))


# ── POST /customers/{customerId}/loan-contracts/{contractId}/reinstate ─────


@bp.post("/customers/<customer_id>/loan-contracts/<contract_id>/reinstate")
@require_auth([ROLE_COLLECTIONS_AGENT])
def reinstate_loan(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    lc = get_loan_contract_or_404(customer_id, contract_id)
    body = get_json()
    expected = parse_version(body)
    check_version(lc, expected)

    if lc["status"] != "DEFAULTED":
        raise err_loan_not_defaulted(
            f"Loan is in {lc['status']}; reinstate requires DEFAULTED."
        )

    # All defaulted payments on this loan must be PAID.
    outstanding = [
        p for p in store.payments.values()
        if p["contract_id"] == contract_id and p["status"] == "DEFAULTED"
    ]
    if outstanding:
        raise err_reinstate_has_outstanding_defaults()

    with store.lock:
        lc["status"] = "ACTIVE"
        stamp_update(lc)
    return success(serialize_loan_contract(lc))


# ── POST /customers/{customerId}/loan-contracts/{contractId}/charge-off ────


@bp.post("/customers/<customer_id>/loan-contracts/<contract_id>/charge-off")
@require_auth([ROLE_COLLECTIONS_AGENT])
def charge_off_loan(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    lc = get_loan_contract_or_404(customer_id, contract_id)
    body = get_json()
    expected = parse_version(body)
    check_version(lc, expected)

    if lc["status"] != "DEFAULTED":
        raise err_loan_not_defaulted(
            f"Loan is in {lc['status']}; charge-off requires DEFAULTED."
        )

    with store.lock:
        lc["status"] = "CHARGED_OFF"
        stamp_update(lc)
        cascade_auto_cancel_gap_riders_for_contract(contract_id)
    return success(serialize_loan_contract(lc))


# ── GET /customers/{customerId}/loan-contracts/{contractId} ────────────────


@bp.get("/customers/<customer_id>/loan-contracts/<contract_id>")
@require_auth([ROLE_LOAN_OFFICER, ROLE_FINANCE_MANAGER, ROLE_COLLECTIONS_AGENT, ROLE_CUSTOMER])
def get_loan(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    lc = get_loan_contract_or_404(customer_id, contract_id)
    return success(serialize_loan_contract(lc))


# ── GET .../payoff-quote ───────────────────────────────────────────────────


@bp.get("/customers/<customer_id>/loan-contracts/<contract_id>/payoff-quote")
@require_auth([ROLE_LOAN_OFFICER, ROLE_FINANCE_MANAGER, ROLE_COLLECTIONS_AGENT, ROLE_CUSTOMER])
def get_loan_payoff_quote(customer_id, contract_id):
    customer = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    lc = get_loan_contract_or_404(customer_id, contract_id)

    variant = request.args.get("variant", "BOOK")
    if variant not in {"BOOK", "CASH"}:
        raise err_invalid_request("variant must be BOOK or CASH.")

    remaining = lc.get("remaining_principal_cents") or 0
    if variant == "BOOK":
        result = loan_payoff_book_cents(remaining)
    else:
        apr = lc.get("apr_bps") or 0
        last_paid_day = lc.get("origination_day_index") or 0
        # Find the most-recent paid_day_index across loan's payments.
        for p in store.payments.values():
            if p["contract_id"] != contract_id:
                continue
            if p["status"] != "PAID":
                continue
            pd = p.get("paid_day_index")
            if pd is not None and pd > last_paid_day:
                last_paid_day = pd
        result = loan_payoff_cash_cents(
            remaining_principal_cents=remaining,
            apr_bps=apr,
            clock_day_index=customer["clock_day_index"],
            last_paid_or_origination_day_index=last_paid_day,
        )
    return success(result)
