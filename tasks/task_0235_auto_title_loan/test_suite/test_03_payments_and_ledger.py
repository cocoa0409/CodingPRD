"""Payments, the allocation waterfall, late fees, and ledger conservation."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    setup_originated_loan,
    setup_delinquent_loan,
    file_loan_lien,
    get_loan,
    set_clock,
    CLOCK_ORIGIN,
    CLOCK_PAST_DUE,
    create_payment_payload,
)

_SERVICER = TEST_USERS["loan_servicer_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Compensating invariant: principal ledger conserved across a REGULAR payment
# ─────────────────────────────────────────────────────────────────────────
def test_principal_ledger_conserved_across_payment(api):
    """PRD §3.6: "the principal applied is the lesser of the new remaining amount and
    principal_balance_cents, and the remaining amount is reduced by that".
    PRD §3.6: "The loan's fees_balance_cents, accrued_interest_cents, and
    principal_balance_cents are each reduced by the corresponding applied amount. This
    arithmetic is exact integer cents."

    Design: Difficulty/compensating_invariant/principal_ledger_conserved_across_payment
    """
    ctx = setup_originated_loan()
    loan_id = ctx["loan"]["id"]
    pay = validate_success(
        api.create_payment(loan_id, create_payment_payload(100000, "REGULAR"), _SERVICER), 201)
    assert pay["principal_applied_cents"] == 100000
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    assert loan["principal_balance_cents"] == 500000
    assert pay["principal_applied_cents"] + loan["principal_balance_cents"] == 600000


def test_principal_conservation_holds_across_two_payments(api):
    """PRD §3.6: "The loan's fees_balance_cents, accrued_interest_cents, and
    principal_balance_cents are each reduced by the corresponding applied amount. This
    arithmetic is exact integer cents."

    Design: Difficulty/compensating_invariant/principal_ledger_conserved_across_payment
    """
    ctx = setup_originated_loan()
    loan_id = ctx["loan"]["id"]
    p1 = validate_success(
        api.create_payment(loan_id, create_payment_payload(100000, "REGULAR"), _SERVICER), 201)
    p2 = validate_success(
        api.create_payment(loan_id, create_payment_payload(150000, "REGULAR"), _SERVICER), 201)
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    applied = p1["principal_applied_cents"] + p2["principal_applied_cents"]
    assert applied + loan["principal_balance_cents"] == 600000


# ─────────────────────────────────────────────────────────────────────────
# Corner: late fee assessment (flat cap on each of two installments)
# ─────────────────────────────────────────────────────────────────────────
def test_late_fee_assessment_two_installments_flat_cap(api):
    """PRD §3.6: "take the installment's principal_due_cents multiplied by 500 basis
    points, divided by 10000, floored to whole cents; raise that to a floor of 1500
    cents if it is lower; then cap it at 5000 cents if it is higher."
    PRD §3.6: "The total assessed is the sum of the per-installment fee over all newly
    past-due installments."

    Design: Corner/calculations/late_fee_assessment_two_installments_flat_cap
    """
    ctx = setup_delinquent_loan(install_dev=False)
    loan = ctx["loan"]
    assert loan["fees_balance_cents"] == 10000
    assert loan["delinquency_status"] == "DELINQUENT"


# ─────────────────────────────────────────────────────────────────────────
# Corner: REGULAR waterfall fees -> interest -> principal
# ─────────────────────────────────────────────────────────────────────────
def test_regular_payment_waterfall_fees_then_interest_then_principal(api):
    """PRD §3.6: "A `REGULAR` payment is allocated by a fixed waterfall in this order:
    fees first, then accrued interest, then principal, then overpayment."
    PRD §3.6: "the fees applied are the lesser of the remaining amount and
    fees_balance_cents, and the remaining amount is reduced by that; the interest
    applied is the lesser of the new remaining amount and accrued_interest_cents".

    Design: Corner/calculations/regular_payment_waterfall_fees_then_interest_then_principal
    """
    ctx = setup_delinquent_loan(install_dev=False)
    loan_id = ctx["loan"]["id"]
    pay = validate_success(
        api.create_payment(loan_id, create_payment_payload(15000, "REGULAR"), _SERVICER), 201)
    assert pay["fees_applied_cents"] == 10000
    assert pay["interest_applied_cents"] == 5000
    assert pay["principal_applied_cents"] == 0
    assert pay["overpayment_cents"] == 0


# ─────────────────────────────────────────────────────────────────────────
# Corner: overpayment refunded on a full REGULAR payoff
# ─────────────────────────────────────────────────────────────────────────
def test_regular_overpayment_refunded_on_full_payoff(api):
    """PRD §3.6: "whatever remains is the overpayment, refunded to the borrower."
    PRD §3.7: "When a REGULAR payment's waterfall allocation (Section 3.6) drives the
    loan's principal_balance_cents, accrued_interest_cents, and fees_balance_cents all
    to zero, the loan's payoff dimension advances OUTSTANDING → PAID_OFF as a system
    transition."

    Design: Corner/calculations/regular_overpayment_refunded_on_full_payoff
    """
    ctx = setup_originated_loan()
    loan_id = ctx["loan"]["id"]
    pay = validate_success(
        api.create_payment(loan_id, create_payment_payload(650000, "REGULAR"), _SERVICER), 201)
    assert pay["principal_applied_cents"] == 600000
    assert pay["overpayment_cents"] == 50000
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    assert loan["payoff_status"] == "PAID_OFF"


# ─────────────────────────────────────────────────────────────────────────
# Corner: insufficient REINSTATEMENT payment rejected
# ─────────────────────────────────────────────────────────────────────────
def test_insufficient_reinstatement_payment_rejected(api):
    """PRD §3.7: "A `REINSTATEMENT` payment must fully cover this computed reinstatement
    amount; a payment that does not cover it in full is rejected with
    `ERR_INSUFFICIENT_PAYMENT` (no partial cures)."

    Design: Corner/validations/insufficient_reinstatement_payment_rejected
    """
    ctx = setup_delinquent_loan(install_dev=False)
    loan_id = ctx["loan"]["id"]
    res = api.create_payment(loan_id, create_payment_payload(400000, "REINSTATEMENT"), _SERVICER)
    validate_error(res, "ERR_INSUFFICIENT_PAYMENT")


# ─────────────────────────────────────────────────────────────────────────
# Corner: PAID_OFF via full REGULAR payment releases the lien + clears vehicle
# ─────────────────────────────────────────────────────────────────────────
def test_paid_off_full_regular_payment_releases_lien(api):
    """PRD §3.7: "This payoff cascades: the title lien transitions `FILED → RELEASED`,
    which in turn sets the collateral vehicle's `lien_state` to `CLEAR` (a depth-two
    chain), and every remaining `SCHEDULED` installment is set to `WAIVED`."

    Design: Corner/state_machines/paid_off_full_regular_payment_releases_lien
    """
    ctx = setup_originated_loan()
    loan_id = ctx["loan"]["id"]
    _filed, lien_id = file_loan_lien(loan_id)
    validate_success(
        api.create_payment(loan_id, create_payment_payload(600000, "REGULAR"), _SERVICER), 201)
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    assert loan["payoff_status"] == "PAID_OFF"
    lien = get_success_data(api.get_title_lien(lien_id, TEST_USERS["title_clerk_headers"]))
    assert lien["status"] == "RELEASED"
    vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], _SERVICER))
    assert vehicle["lien_state"] == "CLEAR"


# ─────────────────────────────────────────────────────────────────────────
# Corner: immediate balance visibility after a payment
# ─────────────────────────────────────────────────────────────────────────
def test_immediate_balance_visible_after_payment(api):
    """PRD §3.6: "the principal applied is the lesser of the new remaining amount and
    principal_balance_cents, and the remaining amount is reduced by that".
    PRD §2.4: "a `version` integer that begins at 1 and increments by one on every
    modification of the resource." — the mutated balance is read back immediately.

    Design: Corner/consistency_model/immediate_balance_visible_after_payment
    """
    ctx = setup_originated_loan()
    loan_id = ctx["loan"]["id"]
    validate_success(
        api.create_payment(loan_id, create_payment_payload(200000, "REGULAR"), _SERVICER), 201)
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    assert loan["principal_balance_cents"] == 400000
