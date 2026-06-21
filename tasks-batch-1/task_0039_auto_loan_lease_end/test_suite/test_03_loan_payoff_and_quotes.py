"""Early-payoff: actuarial vs gross payoff quote divergence, the payoff cascade
(balance -> status -> vehicle), and payoff-amount validation.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_loan, setup_loan_with_payments, setup_paid_off_loan,
    record_payment_payload,
    TEST_USERS, make_borrower_headers,
)

FM = TEST_USERS["finance_manager_headers"]


def test_payoff_quote_actuarial_and_gross_diverge_after_12_payments(api):
    """PRD §3.4: "The **actuarial** payoff, exposed as `actuarial_payoff_cents`, is the binding
    amount the borrower must tender; it equals the actuarial `principal_balance_cents` computed
    after the `payments_made_count` payments already made, and it excludes future,
    as-yet-unearned interest."
    PRD §3.4: "The **gross** payoff, exposed as `gross_payoff_cents`, is an informational naive
    view: the loan's `monthly_payment_cents` multiplied by the number of remaining periods, where
    the remaining periods are `term_months` minus `payments_made_count`; because it bundles future
    interest, it is the larger figure."

    Design: Difficulty/dual_variant_calc/loan_payoff_actuarial_vs_gross_diverge
    """
    customer, vehicle, loan = setup_loan_with_payments(num_payments=12, fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    quote = validate_success(api.get_payoff_quote(loan["id"], borrower), 200)
    assert quote["actuarial_payoff_cents"] == 2039020
    assert quote["gross_payoff_cents"] == 2209440


def test_payoff_quote_unearned_interest_is_gross_minus_actuarial(api):
    """PRD §3.4: "The difference between them — gross minus actuarial — is the unearned-interest
    rebate, returned as `unearned_interest_cents`."

    Design: Difficulty/dual_variant_calc/loan_payoff_actuarial_vs_gross_diverge
    """
    customer, vehicle, loan = setup_loan_with_payments(num_payments=12, fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    quote = validate_success(api.get_payoff_quote(loan["id"], borrower), 200)
    assert quote["unearned_interest_cents"] == 170420


def test_payoff_cascades_balance_status_and_vehicle(api):
    """PRD §3.4: "On success the system writes a `Payment` whose `status` is `POSTED`, whose
    `kind` is `PAYOFF`, and whose `late_fee_cents` is 0; it sets the loan's
    `principal_balance_cents` to 0, moves the loan to the terminal `PAID_OFF` state, sets the
    associated vehicle's `status` to `AVAILABLE`, and increments the loan's `version` by one."

    Design: Difficulty/transitive_cascade/payoff_cascade_balance_vehicle_version
    """
    customer, vehicle, loan = setup_loan(fico_score=760)  # no payments, payoff = financed 2500000
    borrower = make_borrower_headers(customer["id"])
    paid = validate_success(api.payoff_loan(
        loan["id"],
        {"amount_cents": 2_500_000, "expected_loan_version": loan["version"]},
        borrower), 200)
    assert paid["status"] == "PAID_OFF"
    assert paid["principal_balance_cents"] == 0
    vehicle_after = validate_success(api.get_vehicle(vehicle["id"], FM), 200)
    assert vehicle_after["status"] == "AVAILABLE"


def test_payoff_increments_loan_version(api):
    """PRD §3.4: "On success the system writes a `Payment` whose `status` is `POSTED`, whose
    `kind` is `PAYOFF`, and whose `late_fee_cents` is 0; it sets the loan's
    `principal_balance_cents` to 0, moves the loan to the terminal `PAID_OFF` state, sets the
    associated vehicle's `status` to `AVAILABLE`, and increments the loan's `version` by one."

    Design: Difficulty/transitive_cascade/payoff_cascade_balance_vehicle_version
    """
    customer, vehicle, loan = setup_loan(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    paid = validate_success(api.payoff_loan(
        loan["id"],
        {"amount_cents": 2_500_000, "expected_loan_version": loan["version"]},
        borrower), 200)
    assert paid["version"] == loan["version"] + 1


def test_payoff_wrong_amount_returns_payoff_mismatch(api):
    """PRD §3.4: "The tendered `amount_cents` must equal the actuarial payoff quote exactly, or
    the request is rejected with `ERR_PAYOFF_AMOUNT_MISMATCH`."

    Design: Corner/validations/payoff_wrong_amount_returns_payoff_mismatch
    """
    customer, vehicle, loan = setup_loan(fico_score=760)  # actuarial payoff 2500000
    borrower = make_borrower_headers(customer["id"])
    res = api.payoff_loan(
        loan["id"],
        {"amount_cents": 1234567, "expected_loan_version": loan["version"]},
        borrower)
    validate_error(res, "ERR_PAYOFF_AMOUNT_MISMATCH")


def test_payment_on_paid_off_loan_returns_not_payable(api):
    """PRD §3.3: "A scheduled payment is the ordinary monthly remittance. It is permitted only
    when the loan is `CURRENT` or `DELINQUENT`; attempting it on a loan in any other state is
    rejected with `ERR_LOAN_NOT_PAYABLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_payment
    """
    customer, vehicle, loan = setup_paid_off_loan(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    # Wrong amount AND terminal state: the state check (priority 9) precedes the fiscal
    # amount check (priority 13), so ERR_LOAN_NOT_PAYABLE is returned, not the mismatch.
    res = api.record_payment(loan["id"], record_payment_payload(99999, "SCHEDULED"), borrower)
    validate_error(res, "ERR_LOAN_NOT_PAYABLE")


def test_payment_on_terminal_loan_state_check_pre_empts_amount_check(api):
    """PRD §2.8: "Only after these gates pass does the system evaluate the operation-specific
    business rules described in Section 3 (uniqueness, active-rate-card presence, vehicle
    availability, state legality, version freshness, default threshold, payment-amount agreement,
    and mileage-schedule validity), each in the order the relevant workflow narrative
    establishes."
    PRD §3.3: "It is permitted only when the loan is `CURRENT` or `DELINQUENT`; attempting it on
    a loan in any other state is rejected with `ERR_LOAN_NOT_PAYABLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_payment
    """
    customer, vehicle, loan = setup_paid_off_loan(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    res = api.record_payment(loan["id"], record_payment_payload(99999, "SCHEDULED"), borrower)
    validate_error(res, "ERR_LOAN_NOT_PAYABLE")
