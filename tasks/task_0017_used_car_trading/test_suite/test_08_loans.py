"""Tests for PRD §3.6 — Loan application, validation, credit check,
amortization formula, lender APR tiers, approve/reject branches.
"""

import math

import pytest

from test_helpers import (
    api_client,
    create_loan_payload,
    create_purchase_order_payload,
    emit_credit_check_returned,
    make_buyer_headers,
    setup_holding_reservation,
    setup_loan_in_credit_checking,
    validate_error,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# §3.6 Loan param validity
# ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "lender_code,below_min_bp",
    [
        ("LENDER_A", 1499),
        ("LENDER_B", 1999),
        ("LENDER_C", 2499),
    ],
)
def test_down_payment_below_lender_minimum_rejected(api, lender_code, below_min_bp):
    """PRD §3.6: "The down_payment_ratio_bp must be at least the lender's
    minimum: LENDER_A requires at least 1500 basis points, LENDER_B at least
    2000 basis points, LENDER_C at least 2500 basis points; any value below —
    even by a single basis point — fails with ERR_DOWN_PAYMENT_INSUFFICIENT."
    """
    seller, vehicle, listing, buyer, _ = setup_holding_reservation(
        ask_price_cents=5_000_000
    )
    po_payload = create_purchase_order_payload(listing["id"], payment_method="LOAN")
    po_payload["package_code"] = "STANDARD"
    po = validate_success(
        api.create_purchase_order(po_payload, make_buyer_headers(buyer["id"])), 201
    )
    res = api.apply_loan(
        po["id"],
        create_loan_payload(
            lender_code=lender_code,
            requested_principal_cents=2_000_000,
            down_payment_ratio_bp=below_min_bp,
            term_months=36,
        ),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_DOWN_PAYMENT_INSUFFICIENT")


@pytest.mark.parametrize(
    "lender_code,exact_min_bp",
    [
        ("LENDER_A", 1500),
        ("LENDER_B", 2000),
        ("LENDER_C", 2500),
    ],
)
def test_down_payment_at_lender_minimum_succeeds(api, lender_code, exact_min_bp):
    """PRD §3.6: "any value below - even by a single basis point - fails with
    ERR_DOWN_PAYMENT_INSUFFICIENT. The boundary case of exactly the lender
    minimum must succeed."
    """
    seller, vehicle, listing, buyer, _ = setup_holding_reservation(
        ask_price_cents=5_000_000
    )
    po_payload = create_purchase_order_payload(listing["id"], payment_method="LOAN")
    po_payload["package_code"] = "STANDARD"
    po = validate_success(
        api.create_purchase_order(po_payload, make_buyer_headers(buyer["id"])), 201
    )
    res = api.apply_loan(
        po["id"],
        create_loan_payload(
            lender_code=lender_code,
            requested_principal_cents=1_000_000,
            down_payment_ratio_bp=exact_min_bp,
            term_months=36,
        ),
        make_buyer_headers(buyer["id"]),
    )
    loan = validate_success(res, 201)
    assert loan["status"] == "APPLIED"


@pytest.mark.parametrize("bad_term", [11, 13, 18, 24.5, 73, 84])
def test_term_months_outside_allowed_set_rejected(api, bad_term):
    """PRD §3.6: "The term_months must be one of the six allowed values"
    (12, 24, 36, 48, 60, 72) "Any of those parameter violations is rejected
    with ERR_LOAN_PARAMS_INVALID."
    """
    seller, vehicle, listing, buyer, _ = setup_holding_reservation(
        ask_price_cents=5_000_000
    )
    po_payload = create_purchase_order_payload(listing["id"], payment_method="LOAN")
    po_payload["package_code"] = "STANDARD"
    po = validate_success(
        api.create_purchase_order(po_payload, make_buyer_headers(buyer["id"])), 201
    )
    res = api.apply_loan(
        po["id"],
        create_loan_payload(
            lender_code="LENDER_A",
            requested_principal_cents=1_000_000,
            down_payment_ratio_bp=1_500,
            term_months=bad_term,
        ),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_LOAN_PARAMS_INVALID")


def test_requested_principal_zero_or_negative_rejected(api):
    """PRD §3.6: "the requested_principal_cents must be greater than zero".
    """
    seller, vehicle, listing, buyer, _ = setup_holding_reservation(
        ask_price_cents=5_000_000
    )
    po_payload = create_purchase_order_payload(listing["id"], payment_method="LOAN")
    po_payload["package_code"] = "STANDARD"
    po = validate_success(
        api.create_purchase_order(po_payload, make_buyer_headers(buyer["id"])), 201
    )
    res = api.apply_loan(
        po["id"],
        create_loan_payload(
            lender_code="LENDER_A",
            requested_principal_cents=0,
            down_payment_ratio_bp=1_500,
            term_months=36,
        ),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_LOAN_PARAMS_INVALID")


# ──────────────────────────────────────────────────────────
# §3.6 Run credit check / approval
# ──────────────────────────────────────────────────────────


def test_run_credit_check_advances_loan_to_credit_checking(api, admin_headers):
    """PRD §3.6: "A platform admin runs the credit check, advancing the loan
    from APPLIED to CREDIT_CHECKING."
    """
    state = setup_loan_in_credit_checking(
        ask_price_cents=5_000_000,
        lender_code="LENDER_A",
        requested_principal_cents=4_000_000,
        down_payment_ratio_bp=2_000,
        term_months=36,
    )
    assert state["loan"]["status"] == "CREDIT_CHECKING"


def test_credit_check_returned_with_sufficient_score_approves_loan(api, admin_headers):
    """PRD §3.6: "If the buyer's credit_score meets the lender's minimum
    (LENDER_A requires at least 680, LENDER_B at least 640, LENDER_C at
    least 600) and the down-payment ratio is at or above the lender's
    minimum, the loan transitions from CREDIT_CHECKING to APPROVED."
    """
    state = setup_loan_in_credit_checking(
        ask_price_cents=5_000_000,
        lender_code="LENDER_A",
        requested_principal_cents=4_000_000,
        down_payment_ratio_bp=2_000,
        term_months=36,
    )
    emit_credit_check_returned(state["loan"]["id"], credit_score=700)
    refreshed = validate_success(api.get_loan(state["loan"]["id"], admin_headers), 200)
    assert refreshed["status"] == "APPROVED"


def test_credit_check_returned_below_lender_minimum_rejects_loan(api, admin_headers):
    """PRD §3.6: "If the credit score is insufficient or the down-payment
    ratio fails, the loan transitions from CREDIT_CHECKING to REJECTED with
    approved_principal_cents set to zero."

    LENDER_A min credit = 680; score 600 is below — REJECTED.
    """
    state = setup_loan_in_credit_checking(
        ask_price_cents=5_000_000,
        lender_code="LENDER_A",
        requested_principal_cents=4_000_000,
        down_payment_ratio_bp=2_000,
        term_months=36,
    )
    emit_credit_check_returned(state["loan"]["id"], credit_score=600)
    refreshed = validate_success(api.get_loan(state["loan"]["id"], admin_headers), 200)
    assert refreshed["status"] == "REJECTED"
    assert refreshed["approved_principal_cents"] == 0


# ──────────────────────────────────────────────────────────
# §3.6 Amortization formula — pinned five-step order
# ──────────────────────────────────────────────────────────


def test_amortization_formula_lender_a_580bp_known_inputs(api, admin_headers):
    """PRD §3.6: pinned five-step amortization. Inputs: agreed_price=5_000_000,
    requested=4_000_000, ratio=2000bp, term=36, credit=700 (LENDER_A APR 580bp
    because score >= 680 but < 740).

    PRD §3.6: "Second, the maximum principal is computed as the order's
    agreed_price_cents minus the down-payment requirement, where the
    down-payment requirement is the order's agreed_price_cents multiplied by
    the buyer's down_payment_ratio_bp divided by ten thousand and rounded up
    to the next whole cent."
    PRD §3.6: "Third, the approved_principal_cents is the smaller of the
    buyer's requested_principal_cents and the maximum principal just
    computed."
    PRD §3.6: "Fourth, the monthly_payment_cents is the standard amortisation
    ... and round the whole thing up to the next whole cent (single ceiling
    at the end)."
    PRD §3.6: "Fifth, the total_interest_cents is the monthly_payment_cents
    multiplied by the term_months minus the approved_principal_cents (no
    further rounding)."

    Manual derivation:
      down = ceil(5_000_000 * 2000 / 10000) = ceil(1_000_000) = 1_000_000
      max_principal = 5_000_000 - 1_000_000 = 4_000_000
      approved = min(4_000_000, 4_000_000) = 4_000_000
      monthly_rate = 580/10000/12 = 0.0048333...
      monthly_payment = ceil(4_000_000 * r / (1 - (1+r)^-36)) = 121_326
      total_interest = 121_326 * 36 - 4_000_000 = 367_736
    """
    state = setup_loan_in_credit_checking(
        ask_price_cents=5_000_000,
        lender_code="LENDER_A",
        requested_principal_cents=4_000_000,
        down_payment_ratio_bp=2_000,
        term_months=36,
    )
    emit_credit_check_returned(state["loan"]["id"], credit_score=700)
    loan = validate_success(api.get_loan(state["loan"]["id"], admin_headers), 200)
    assert loan["status"] == "APPROVED"
    assert loan["approved_principal_cents"] == 4_000_000
    assert loan["monthly_payment_cents"] == 121_326
    assert loan["total_interest_cents"] == 367_736


def test_amortization_total_interest_invariant(api, admin_headers):
    """PRD §3.6: "the total_interest_cents is the monthly_payment_cents
    multiplied by the term_months minus the approved_principal_cents".
    Invariant must hold after any approval.
    """
    state = setup_loan_in_credit_checking(
        ask_price_cents=5_000_000,
        lender_code="LENDER_A",
        requested_principal_cents=3_000_000,
        down_payment_ratio_bp=2_500,
        term_months=48,
    )
    emit_credit_check_returned(state["loan"]["id"], credit_score=720)
    loan = validate_success(api.get_loan(state["loan"]["id"], admin_headers), 200)
    expected_interest = (
        loan["monthly_payment_cents"] * loan["term_months"]
        - loan["approved_principal_cents"]
    )
    assert loan["total_interest_cents"] == expected_interest


# ──────────────────────────────────────────────────────────
# §3.6 Cancellation (APPLIED → CANCELLED)
# ──────────────────────────────────────────────────────────


def test_buyer_cancels_loan_in_applied(api):
    """PRD §3.6: "A buyer may also cancel before this step, taking the loan
    from APPLIED directly to CANCELLED."
    """
    seller, vehicle, listing, buyer, _ = setup_holding_reservation(
        ask_price_cents=5_000_000
    )
    po_payload = create_purchase_order_payload(listing["id"], payment_method="LOAN")
    po_payload["package_code"] = "STANDARD"
    po = validate_success(
        api.create_purchase_order(po_payload, make_buyer_headers(buyer["id"])), 201
    )
    loan = validate_success(
        api.apply_loan(
            po["id"],
            create_loan_payload(
                lender_code="LENDER_A",
                requested_principal_cents=2_000_000,
                down_payment_ratio_bp=1_500,
                term_months=36,
            ),
            make_buyer_headers(buyer["id"]),
        ),
        201,
    )
    cancelled = validate_success(
        api.cancel_loan(loan["id"], make_buyer_headers(buyer["id"])), 200
    )
    assert cancelled["status"] == "CANCELLED"
