"""Cross-entity state dependencies + compensating-action invariants.

Plan activation depending on Loan.status; PSLF discharge depending on Loan's
computed pslf_qualifying_payment_count; reversal-of-applied-payment
preserves the money invariant; PSLF count excludes REVERSED payments.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    set_clock, create_borrower, create_loan, walk_loan_to_repayment,
    setup_borrower_and_loan_in_repayment,
    setup_loan_with_active_standard_plan,
    create_repayment_plan, create_and_activate_plan,
    create_and_certify_qualifying_employment,
    file_and_begin_review_discharge,
    post_payment, post_and_apply_payment,
    make_borrower_headers,
    TEST_USERS, ApiErrorId,
)


LS = TEST_USERS["loan_servicer_headers"]


def test_plan_activation_requires_loan_in_repayment(api):
    """Activating a PENDING RepaymentPlan whose parent Loan is in IN_SCHOOL
    (not REPAYMENT) fails with ERR_INVALID_STATE.

    PRD §3.5: "Activation has three preconditions: the plan must currently be
    PENDING, the parent loan must be in REPAYMENT, and no other plan with the
    same loan_id may already be ACTIVE."
    PRD §3.5: "the first surfaces as ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/plan_activation_requires_loan_repayment_state
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Cross1", ssn_last4="0060")
    # Loan is created with version=1 in ORIGINATED status.
    loan = create_loan(
        borrower["id"], loan_type="DIRECT_UNSUB",
        principal_cents=100_000, interest_rate_bps=500,
        disbursement_date="2026-06-01T00:00:00Z",
    )
    plan = create_repayment_plan(
        loan["id"], loan["version"],
        plan_type="STANDARD", effective_date="2026-06-01T00:00:00Z",
    )
    # Now move loan to IN_SCHOOL (not REPAYMENT).
    validate_success(api.enter_school(loan["id"], LS), 200)

    res = api.activate_repayment_plan(plan["id"], LS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_pslf_discharge_requires_120_qualifying_payments(api):
    """Approve PSLF discharge against a loan whose pslf_qualifying_payment_count
    is zero is rejected with ERR_PSLF_INSUFFICIENT_PAYMENTS.

    PRD §3.9: "when discharge_type is PSLF, the loan's
    pslf_qualifying_payment_count must be at least 120, and a lower value
    rejects with ERR_PSLF_INSUFFICIENT_PAYMENTS."

    Design: Difficulty/cross_entity_state_dependency/discharge_approve_pslf_requires_loan_qualifying_count
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Cross2", ssn_last4="0061",
    )
    app = file_and_begin_review_discharge(
        loan["id"], borrower["id"], discharge_type="PSLF")

    res = api.approve_discharge(
        app["id"],
        {"review_notes": "n/a",
         "expected_application_version": app["version"]},
        LS,
    )
    validate_error(res, ApiErrorId.ERR_PSLF_INSUFFICIENT_PAYMENTS.value)


def test_payment_reverse_preserves_loan_balances(api):
    """Applying a payment then reversing it returns the loan's
    principal_balance_cents and accrued_interest_cents to their pre-apply
    values.

    PRD §3.6: "In this case, principal_applied_cents and interest_applied_cents
    are subtracted back from the loan's principal_balance_cents and
    accrued_interest_cents respectively — the compensating motion that
    preserves the system's reversal invariant."

    Design: Difficulty/compensating_invariant/payment_reverse_preserves_total_outstanding_plus_applied
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Inv1", ssn_last4="0080",
        loan_type="DIRECT_UNSUB", principal_cents=1_000_000,
        interest_rate_bps=500,
    )
    pay = post_and_apply_payment(
        loan["id"], borrower["id"],
        amount_cents=50_000, payment_date="2026-06-01T00:00:00Z",
    )
    assert pay["status"] == "APPLIED"

    validate_success(api.reverse_payment(pay["id"], LS), 200)

    loan_after = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_after["principal_balance_cents"] == 1_000_000, (
        f"Reversal must restore principal_balance to 1_000_000, "
        f"got {loan_after['principal_balance_cents']}"
    )
    assert loan_after["accrued_interest_cents"] == 0, (
        f"Reversal must restore accrued_interest to 0, "
        f"got {loan_after['accrued_interest_cents']}"
    )


def test_pslf_count_excludes_reversed_payments(api):
    """A qualifying payment counts in pslf_qualifying_payment_count when APPLIED
    and stops counting once REVERSED.

    PRD §3.6: "Reversal moves the payment to REVERSED, recomputes
    pslf_qualifying_payment_count for the loan (because REVERSED payments are
    excluded from the count), and increments both Payment.version and
    Loan.version."

    Design: Difficulty/compensating_invariant/pslf_count_excludes_reversed_payments_invariant
    """
    borrower, loan, _plan = setup_loan_with_active_standard_plan(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Inv2", ssn_last4="0081",
        loan_type="DIRECT_UNSUB", principal_cents=3_000_000,
        interest_rate_bps=533,
        disbursement_date="2025-01-01T00:00:00Z",
        plan_effective_date="2025-06-01T00:00:00Z",
    )
    create_and_certify_qualifying_employment(
        borrower["id"],
        employer_name="Dept of W", employer_type="GOVERNMENT",
        period_start="2025-01-01T00:00:00Z",
        period_end="2027-12-31T00:00:00Z",
    )
    # Post + apply a single qualifying payment dated after the loan reached
    # REPAYMENT (per PRD §3.7 predicate 5).
    post_and_apply_payment(
        loan["id"], borrower["id"],
        amount_cents=100_000, payment_date="2026-06-01T00:00:00Z",
    )
    loan_mid = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_mid["pslf_qualifying_payment_count"] == 1, (
        f"Expected pslf_qualifying_payment_count == 1 after APPLIED qualifying "
        f"payment, got {loan_mid['pslf_qualifying_payment_count']}"
    )
    # Find the payment and reverse it.
    from prd_bench_local_runner.testing import validate_paginated
    pays_res = api.list_payments(LS, params={"loan_id": loan["id"]})
    pays, _meta = validate_paginated(pays_res)
    applied_pay = next(p for p in pays if p["status"] == "APPLIED")
    validate_success(api.reverse_payment(applied_pay["id"], LS), 200)

    loan_after = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_after["pslf_qualifying_payment_count"] == 0, (
        f"After reversal, expected pslf_qualifying_payment_count == 0, "
        f"got {loan_after['pslf_qualifying_payment_count']}"
    )
