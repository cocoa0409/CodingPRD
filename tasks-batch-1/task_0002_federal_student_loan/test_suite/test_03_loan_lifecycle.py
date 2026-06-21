"""Loan + DischargeApplication state-machine tests.

Covers cyclic transitions (REPAYMENT → DEFERMENT → REPAYMENT), branching
(APPROVE vs DENY), terminal lockdown (PAID_OFF), invalid transitions, idempotency,
and capitalization on resume-from-DEFERMENT.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    set_clock, create_borrower, create_loan, walk_loan_to_repayment,
    setup_borrower_and_loan_in_repayment,
    setup_discharge_application_under_review,
    make_borrower_headers,
    post_payment,
    TEST_USERS, ApiErrorId,
)


LS = TEST_USERS["loan_servicer_headers"]


def test_loan_cyclic_repayment_deferment_repayment(api):
    """Borrower-initiated DEFERMENT followed by LoanServicer resume returns the
    loan to REPAYMENT — Loan's status machine includes A→B→A cycles.

    PRD §3.4: "A deferment is requested directly against the loan, transitioning
    it from REPAYMENT to DEFERMENT; the resulting StatusChange carries
    reason_code DEFERMENT_REQUEST."
    PRD §3.4: "Either pause is closed out by a LoanServicer returning the loan
    to REPAYMENT via the resume action; the resume transition is the
    capitalization moment, and is reachable from either DEFERMENT or FORBEARANCE."

    Design: Difficulty/non_linear_state_machine/loan_cyclic_repayment_deferment_repayment
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Cyc B", ssn_last4="0010",
    )
    res = api.request_deferment(loan["id"], make_borrower_headers(borrower["id"]))
    loan_def = validate_success(res, 200)
    assert loan_def["status"] == "DEFERMENT"

    res = api.resume_repayment(loan["id"], LS)
    loan_repay = validate_success(res, 200)
    assert loan_repay["status"] == "REPAYMENT"


def test_discharge_application_branches_to_approved_cascading_to_loan(api):
    """The APPROVE branch fires the 3-level cascade — application to APPROVED,
    parent Loan to DISCHARGED with balance zeroed.

    PRD §3.9: "On a successful approve, review_notes is persisted, the
    application's status advances to APPROVED, and a two-step cascade fires.
    First, the parent loan transitions from REPAYMENT to DISCHARGED, with
    principal_balance_cents and accrued_interest_cents both being set to zero,
    and a StatusChange is written with reason_code DISCHARGE_APPROVED."

    Design: Difficulty/non_linear_state_machine/discharge_application_branching_approve_or_deny
    """
    borrower, loan, app = setup_discharge_application_under_review(
        clock_iso="2026-06-01T00:00:00Z",
        is_veteran=True,
        discharge_type="VETERAN_TOTAL_DISABILITY",
        full_name="Vet B", ssn_last4="0011",
    )
    res = api.approve_discharge(
        app["id"],
        {"review_notes": "VA disability rating verified",
         "expected_application_version": app["version"]},
        LS,
    )
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"

    loan_after = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_after["status"] == "DISCHARGED"
    assert loan_after["principal_balance_cents"] == 0


def test_discharge_deny_does_not_cascade_to_loan(api):
    """The DENY branch leaves the parent Loan unchanged — no cascade fires.

    PRD §3.9: "Denial moves the application from UNDER_REVIEW to DENIED and
    persists any supplied review_notes on the application; the version advances
    and updated_at refreshes."

    Design: Corner/state_machines/discharge_application_branching_deny_no_loan_cascade
    """
    borrower, loan, app = setup_discharge_application_under_review(
        clock_iso="2026-06-01T00:00:00Z",
        is_veteran=False,
        discharge_type="VETERAN_TOTAL_DISABILITY",
        full_name="Dny B", ssn_last4="0012",
    )
    res = api.deny_discharge(
        app["id"], {"review_notes": "documentation incomplete"}, LS)
    denied = validate_success(res, 200)
    assert denied["status"] == "DENIED"

    loan_after = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_after["status"] == "REPAYMENT"


def test_originated_cannot_graduate_directly(api):
    """Calling /graduate on a loan still in ORIGINATED (no enter-school yet)
    is rejected with ERR_INVALID_STATE.

    PRD §3.2: "Each transition is reachable only from the specific from-state
    declared below; an attempt to invoke a transition from any other from-state
    is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/loan_originated_cannot_graduate_directly
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Inv B", ssn_last4="0005")
    loan = create_loan(borrower["id"])  # ORIGINATED, no enter-school
    res = api.graduate(loan["id"], LS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_paid_off_is_terminal_no_resume(api):
    """Once a loan reaches PAID_OFF, resume-repayment is rejected with
    ERR_INVALID_STATE — PAID_OFF is a terminal state.

    PRD §3.4: "An attempt to resume a loan that is not currently in one of those
    two paused states fails with ERR_INVALID_STATE."

    Design: Corner/state_machines/loan_paid_off_is_terminal_no_resume
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Pay B", ssn_last4="0006")
    loan = create_loan(borrower["id"], principal_cents=100)
    loan = walk_loan_to_repayment(loan["id"])
    # Borrower posts 100-cent payment, LoanServicer applies — auto PAID_OFF.
    pay = post_payment(loan["id"], borrower["id"],
                       amount_cents=100, payment_date="2026-06-01T00:00:00Z")
    applied = validate_success(api.apply_payment(pay["id"], LS), 200)
    assert applied["status"] == "APPLIED"

    loan_after = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_after["status"] == "PAID_OFF"

    res = api.resume_repayment(loan["id"], LS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_idempotency_double_enter_school_rejected(api):
    """A second POST /enter-school after the first is rejected with
    ERR_INVALID_STATE — the loan is now IN_SCHOOL, not ORIGINATED.

    PRD §3.2: "Each transition is reachable only from the specific from-state
    declared below; an attempt to invoke a transition from any other from-state
    is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/idempotency_double_enter_school_second_call_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Idm B", ssn_last4="0008")
    loan = create_loan(borrower["id"])
    validate_success(api.enter_school(loan["id"], LS), 200)
    res = api.enter_school(loan["id"], LS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_resume_from_deferment_capitalizes_accrued_interest(api):
    """Resume from DEFERMENT moves accrued_interest_cents (4560) into both
    principal_balance_cents and capitalized_interest_cents; accrued is zeroed.

    PRD §3.3: "When a loan returns from DEFERMENT to REPAYMENT or from
    FORBEARANCE to REPAYMENT (both transitions invoked by a LoanServicer after
    the borrower-initiated pause ends), the value currently held in
    accrued_interest_cents is added to principal_balance_cents, the same amount
    is added to the running capitalized_interest_cents tally, and
    accrued_interest_cents is reset to zero."

    Design: Corner/state_machines/deferment_to_repayment_capitalizes_accrued_interest
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Cap B", ssn_last4="0007")
    loan = create_loan(
        borrower["id"], loan_type="DIRECT_UNSUB",
        principal_cents=1_111_111, interest_rate_bps=500,
        disbursement_date="2026-06-01T00:00:00Z",
    )
    walk_loan_to_repayment(loan["id"])
    # Advance 30 days — accrued = 4560 cents.
    set_clock("2026-07-01T00:00:00Z")
    validate_success(
        api.request_deferment(loan["id"], make_borrower_headers(borrower["id"])),
        200,
    )
    res = api.resume_repayment(loan["id"], LS)
    loan_after = validate_success(res, 200)
    assert loan_after["principal_balance_cents"] == 1_115_671, (
        f"After capitalization principal_balance expected 1115671, "
        f"got {loan_after['principal_balance_cents']}"
    )
    assert loan_after["accrued_interest_cents"] == 0
    assert loan_after["capitalized_interest_cents"] == 4560
