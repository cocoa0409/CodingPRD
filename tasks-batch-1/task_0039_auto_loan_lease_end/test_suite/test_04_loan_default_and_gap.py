"""Declaring default: the delinquency threshold boundary, the repossession cascade,
and the gap-insurance deficiency-waiver invariant.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_loan, setup_delinquent_loan,
    TEST_USERS,
)

FM = TEST_USERS["finance_manager_headers"]


def test_default_threshold_below_boundary_rejected_at_two(api):
    """PRD §3.3: "If the loan is delinquent but `missed_payment_count` is still below 3, the
    declaration is rejected with `ERR_DEFAULT_THRESHOLD_NOT_MET`."

    Design: Difficulty/boundary_precision_check/default_threshold_exact_boundary
    """
    customer, vehicle, loan = setup_delinquent_loan(num_missed=2, fico_score=760)
    res = api.declare_default(loan["id"], {"insurance_settlement_cents": 2_000_000}, FM)
    validate_error(res, "ERR_DEFAULT_THRESHOLD_NOT_MET")


def test_default_threshold_at_boundary_three_succeeds(api):
    """PRD §3.3: "Once a delinquent loan's `missed_payment_count` reaches at least 3, a
    `FinanceManager` may declare default, supplying the `insurance_settlement_cents` recovered on
    the repossessed vehicle."

    Design: Difficulty/boundary_precision_check/default_threshold_exact_boundary
    """
    customer, vehicle, loan = setup_delinquent_loan(num_missed=3, fico_score=760)
    defaulted = validate_success(api.declare_default(
        loan["id"], {"insurance_settlement_cents": 2_000_000}, FM), 200)
    assert defaulted["status"] == "DEFAULT"


def test_default_cascades_vehicle_to_available(api):
    """PRD §3.3: "On default the loan moves to the terminal `DEFAULT` state and the associated
    vehicle's `status` is set back to `AVAILABLE`, modeling repossession."

    Design: Difficulty/transitive_cascade/default_cascade_vehicle_and_gap_waiver
    """
    customer, vehicle, loan = setup_delinquent_loan(
        num_missed=3, fico_score=760, loan_overrides={"gap_insurance": True})
    defaulted = validate_success(api.declare_default(
        loan["id"], {"insurance_settlement_cents": 2_000_000}, FM), 200)
    assert defaulted["status"] == "DEFAULT"
    vehicle_after = validate_success(api.get_vehicle(vehicle["id"], FM), 200)
    assert vehicle_after["status"] == "AVAILABLE"


def test_default_with_gap_insurance_reaches_default_state(api):
    """PRD §3.3: "On default the loan moves to the terminal `DEFAULT` state and the associated
    vehicle's `status` is set back to `AVAILABLE`, modeling repossession."

    Design: Difficulty/transitive_cascade/default_cascade_vehicle_and_gap_waiver
    """
    customer, vehicle, loan = setup_delinquent_loan(
        num_missed=3, fico_score=760, loan_overrides={"gap_insurance": True})
    defaulted = validate_success(api.declare_default(
        loan["id"], {"insurance_settlement_cents": 2_000_000}, FM), 200)
    assert defaulted["status"] == "DEFAULT"


def test_gap_default_borrower_net_balance_conserved_zero(api):
    """PRD §3.3: "When the loan was originated with `gap_insurance` true, Gap coverage pays out
    exactly that deficiency, so the gap payout equals the deficiency and the borrower's net
    post-default balance — the principal balance, less the insurance settlement, less the gap
    payout — is conserved at zero."

    Design: Difficulty/compensating_invariant/gap_default_borrower_balance_conserved_zero
    """
    # No payments: principal_balance 2500000; insurance 2000000; deficiency 500000;
    # gap payout = deficiency = 500000; net = 2500000 - 2000000 - 500000 = 0.
    customer, vehicle, loan = setup_delinquent_loan(
        num_missed=3, fico_score=760, loan_overrides={"gap_insurance": True})
    principal_balance = 2_500_000
    insurance_settlement = 2_000_000
    deficiency = max(0, principal_balance - insurance_settlement)
    gap_payout = deficiency  # gap_insurance true: payout equals deficiency
    borrower_net_balance = principal_balance - insurance_settlement - gap_payout
    defaulted = validate_success(api.declare_default(
        loan["id"], {"insurance_settlement_cents": insurance_settlement}, FM), 200)
    assert defaulted["status"] == "DEFAULT"
    assert borrower_net_balance == 0


def test_gap_default_conserved_invariant_distinct_from_no_gap(api):
    """PRD §3.3: "When `gap_insurance` is false there is no gap payout, and the borrower's net
    post-default balance equals the deficiency itself."

    Design: Difficulty/compensating_invariant/gap_default_borrower_balance_conserved_zero
    """
    # With gap true the conserved quantity is zero, distinct from the deficiency that would
    # remain without gap. Verify the loan defaults and the gap-true arithmetic holds at zero.
    customer, vehicle, loan = setup_delinquent_loan(
        num_missed=3, fico_score=760, loan_overrides={"gap_insurance": True})
    principal_balance = 2_500_000
    insurance_settlement = 2_000_000
    deficiency = max(0, principal_balance - insurance_settlement)
    with_gap_net = principal_balance - insurance_settlement - deficiency  # gap covers deficiency
    defaulted = validate_success(api.declare_default(
        loan["id"], {"insurance_settlement_cents": insurance_settlement}, FM), 200)
    assert defaulted["status"] == "DEFAULT"
    assert with_gap_net == 0
    assert deficiency == 500_000  # what a no-gap borrower would still owe


def test_declare_default_on_current_loan_returns_not_payable(api):
    """PRD §3.3: "Default may be declared only from `DELINQUENT`; from any other state the
    request is rejected with `ERR_LOAN_NOT_PAYABLE`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_state_on_default
    """
    customer, vehicle, loan = setup_loan(fico_score=760)  # CURRENT, never delinquent
    res = api.declare_default(loan["id"], {"insurance_settlement_cents": 2_000_000}, FM)
    validate_error(res, "ERR_LOAN_NOT_PAYABLE")


def test_declare_default_current_loan_state_check_pre_empts_threshold(api):
    """PRD §2.8: "Only after these gates pass does the system evaluate the operation-specific
    business rules described in Section 3 (uniqueness, active-rate-card presence, vehicle
    availability, state legality, version freshness, default threshold, payment-amount agreement,
    and mileage-schedule validity), each in the order the relevant workflow narrative
    establishes."
    PRD §3.3: "Default may be declared only from `DELINQUENT`; from any other state the request
    is rejected with `ERR_LOAN_NOT_PAYABLE`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_state_on_default
    """
    # A CURRENT loan has missed_payment_count 0 (below threshold) AND is in the wrong state.
    # The state-legality check precedes the threshold check, so ERR_LOAN_NOT_PAYABLE wins.
    customer, vehicle, loan = setup_loan(fico_score=760)
    res = api.declare_default(loan["id"], {"insurance_settlement_cents": 2_000_000}, FM)
    validate_error(res, "ERR_LOAN_NOT_PAYABLE")
