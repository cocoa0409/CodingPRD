"""Loan request, approval, repayment lifecycle, max-loan calculation,
one-outstanding-loan invariant, and default cascade (PRD §3.5,
§2.13)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ABSOLUTE_LOAN_CAP_CENTS,
    ApiErrorId,
    TEST_USERS,
    api_client,
    advance_clock,
    approve_loan,
    assert_loan,
    assert_loan_repayment,
    create_loan_payload,
    create_loan_repayment_payload,
    make_participant_headers,
    post_loan_repayment,
    request_and_approve_loan,
    request_loan,
    setup_loan_lifecycle,
    setup_participant_with_balance,
    validate_error,
    validate_success,
)


# ===========================================================================
# term_months bounds — PRD §3.5
# ===========================================================================
def test_loan_request_term_zero_rejected(api):
    """PRD §3.5: "term_months must be a whole number in the closed
    range one through sixty; an out-of-range value is rejected with
    ERR_LOAN_TERM_INVALID."

    Claim: term_months=0 -> ERR_LOAN_TERM_INVALID.
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=2_000_000, cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    headers = make_participant_headers(p["id"])
    res = api.create_loan(
        plan["id"], p["id"],
        create_loan_payload(requested_amount_cents=100_000, term_months=0),
        headers,
    )
    validate_error(
        res, ApiErrorId.ERR_LOAN_TERM_INVALID.value, expected_status=400,
    )


def test_loan_request_term_61_rejected(api):
    """PRD §3.5: "term_months must be a whole number in the closed
    range one through sixty; an out-of-range value is rejected with
    ERR_LOAN_TERM_INVALID."

    Claim: term_months=61 -> ERR_LOAN_TERM_INVALID.
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=2_000_000, cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    headers = make_participant_headers(p["id"])
    res = api.create_loan(
        plan["id"], p["id"],
        create_loan_payload(requested_amount_cents=100_000, term_months=61),
        headers,
    )
    validate_error(
        res, ApiErrorId.ERR_LOAN_TERM_INVALID.value, expected_status=400,
    )


def test_loan_request_term_60_succeeds(api):
    """PRD §3.5: term_months "in the closed range one through sixty".

    Claim: term_months=60 (upper boundary) succeeds -> 201.
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=2_000_000, cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    headers = make_participant_headers(p["id"])
    res = api.create_loan(
        plan["id"], p["id"],
        create_loan_payload(requested_amount_cents=100_000, term_months=60),
        headers,
    )
    loan = validate_success(res, 201)
    assert_loan(loan)
    assert loan["status"] == "REQUESTED"
    assert loan["term_months"] == 60


# ===========================================================================
# Provisional outstanding on request — PRD §3.5
# ===========================================================================
def test_loan_request_outstanding_provisional_equals_requested(api):
    """PRD §3.5: "A successful request produces a Loan row in
    REQUESTED status with outstanding_principal_cents set provisionally
    to requested_amount_cents (it is not yet debited from the
    participant's balance)."

    Claim: a freshly REQUESTED loan has
    outstanding_principal_cents == requested_amount_cents.
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=2_000_000, cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    loan = request_loan(
        plan["id"], p["id"],
        requested_amount_cents=300_000, term_months=12,
    )
    assert loan["status"] == "REQUESTED"
    assert loan["outstanding_principal_cents"] == 300_000


# ===========================================================================
# One outstanding loan per participant — PRD §3.5
# ===========================================================================
def test_second_loan_request_blocked_by_outstanding_requested(api):
    """PRD §3.5: "A new loan request is rejected with
    ERR_LOAN_ALREADY_OUTSTANDING if the participant already has
    another Loan in REQUESTED or ACTIVE status."

    Claim: second loan request while first is REQUESTED -> 409
    ERR_LOAN_ALREADY_OUTSTANDING.

    # difficulty: resource_temporal_overlap/loan_existence_window_one_outstanding
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=4_000_000, cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    request_loan(
        plan["id"], p["id"],
        requested_amount_cents=200_000, term_months=10,
    )
    headers = make_participant_headers(p["id"])
    res = api.create_loan(
        plan["id"], p["id"],
        create_loan_payload(
            requested_amount_cents=100_000, term_months=10,
        ),
        headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_LOAN_ALREADY_OUTSTANDING.value,
        expected_status=409,
    )


def test_loan_slot_reopens_after_rejection(api, admin_headers):
    """PRD §3.5: "Rejection ... transitions the loan from REQUESTED to
    REJECTED, which is terminal."
    PRD §3.5: "A new loan request is rejected with
    ERR_LOAN_ALREADY_OUTSTANDING if the participant already has
    another Loan in REQUESTED or ACTIVE status."

    Claim: after the first loan reaches the terminal REJECTED state,
    a new loan request succeeds — the existence-interval closes at
    the terminal state.

    # difficulty: resource_temporal_overlap/loan_existence_window_one_outstanding
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=4_000_000, cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    loan1 = request_loan(
        plan["id"], p["id"],
        requested_amount_cents=200_000, term_months=10,
    )
    # Reject loan1.
    rej = validate_success(
        api.reject_loan(
            plan["id"], p["id"], loan1["id"], None, admin_headers,
        ),
        200,
    )
    assert rej["status"] == "REJECTED"
    # Now a new loan should succeed.
    loan3 = request_loan(
        plan["id"], p["id"],
        requested_amount_cents=100_000, term_months=10,
    )
    assert loan3["status"] == "REQUESTED"
    assert loan3["id"] != loan1["id"]


# ===========================================================================
# Max loan amount — PRD §3.5 absolute cap
# ===========================================================================
def test_loan_exceeds_absolute_cap_rejected(api):
    """PRD §3.5: "second, it computes the IRS-style cap as the smaller
    of (a) the integer floor of the vested balance divided by two ...
    and (b) the absolute loan cap, which is fixed at $50,000 (that is,
    5,000,000 cents)."

    Claim: with vested_balance = 16,000,000, 50%-of-vested =
    8,000,000 but cap binds at 5,000,000. Request for 5,000,001 ->
    ERR_LOAN_EXCEEDS_MAX. Request for 5,000,000 -> 201 (boundary).

    # difficulty: combinatorial_formula/max_loan_amount_three_input_non_linear
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=16_000_000,
        cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    headers = make_participant_headers(p["id"])
    # Boundary: request exactly the cap, should succeed.
    res_ok = api.create_loan(
        plan["id"], p["id"],
        create_loan_payload(
            requested_amount_cents=ABSOLUTE_LOAN_CAP_CENTS,
            term_months=12,
        ),
        headers,
    )
    loan = validate_success(res_ok, 201)
    assert loan["requested_amount_cents"] == ABSOLUTE_LOAN_CAP_CENTS
    # The first slot is occupied now; reject it to free the slot for
    # the over-cap test.
    api.reject_loan(
        plan["id"], p["id"], loan["id"], None,
        TEST_USERS["admin_headers"],
    )
    # Over-cap: request cap+1, should be rejected with
    # ERR_LOAN_EXCEEDS_MAX.
    res_bad = api.create_loan(
        plan["id"], p["id"],
        create_loan_payload(
            requested_amount_cents=ABSOLUTE_LOAN_CAP_CENTS + 1,
            term_months=12,
        ),
        headers,
    )
    validate_error(
        res_bad,
        ApiErrorId.ERR_LOAN_EXCEEDS_MAX.value,
        expected_status=422,
    )


def test_loan_exceeds_absolute_cap_rejected_alternate(api):
    """PRD §3.5: same absolute-cap rule, exercised via a slightly
    different balance to give the difficulty instance two tests.

    # difficulty: combinatorial_formula/max_loan_amount_three_input_non_linear
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=16_000_000,
        cliff_years=1,
        starting_clock="2026-02-01", hire_date="2020-03-15",
    )
    headers = make_participant_headers(p["id"])
    res_bad = api.create_loan(
        plan["id"], p["id"],
        create_loan_payload(
            requested_amount_cents=ABSOLUTE_LOAN_CAP_CENTS * 2,
            term_months=24,
        ),
        headers,
    )
    validate_error(
        res_bad,
        ApiErrorId.ERR_LOAN_EXCEEDS_MAX.value,
        expected_status=422,
    )


# ===========================================================================
# Approve loan — side effects PRD §3.5
# ===========================================================================
def test_loan_approve_pins_origination_and_next_due(api):
    """PRD §3.5: "On a successful approval, the system pins
    approved_amount_cents to requested_amount_cents exactly ... sets
    origination_date to the plan clock's current date, sets
    next_due_date to the origination date plus 30 days, and computes
    monthly_payment_cents as approved_amount_cents divided by
    term_months rounded half up to a whole cent."

    Claim: after approve, approved == requested, origination_date is
    set, next_due_date is origination+30 days, monthly_payment is the
    rounded division.
    """
    plan, p, loan = setup_loan_lifecycle(
        target_balance_cents=4_000_000,
        requested_amount_cents=1_000_000,
        term_months=12,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    assert loan["status"] == "ACTIVE"
    assert loan["approved_amount_cents"] == 1_000_000
    assert loan["origination_date"] is not None
    # next_due_date = origination + 30 days
    from datetime import date as _date, timedelta as _td
    od = _date.fromisoformat(loan["origination_date"])
    nd = _date.fromisoformat(loan["next_due_date"])
    assert nd == od + _td(days=30)
    # round_half_up(1_000_000 / 12) = 83333
    assert loan["monthly_payment_cents"] == 83_333


# ===========================================================================
# Repayment posting — PRD §3.5
# ===========================================================================
def test_loan_repayment_decrements_outstanding(api):
    """PRD §3.5: "The loan's outstanding_principal_cents is
    decremented by payment_amount_cents".

    Claim: after one 100k repayment on a 1M loan, outstanding falls
    to 900k.
    """
    plan, p, loan = setup_loan_lifecycle(
        target_balance_cents=4_000_000,
        requested_amount_cents=1_000_000,
        term_months=10,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    rep = post_loan_repayment(
        plan["id"], p["id"], loan["id"],
        payment_amount_cents=100_000,
    )
    assert_loan_repayment(rep)
    loan_after = validate_success(
        api.get_loan(
            plan["id"], p["id"], loan["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    assert loan_after["outstanding_principal_cents"] == 900_000
    assert loan_after["payments_made"] == 1
    assert loan_after["status"] == "ACTIVE"


def test_loan_overpayment_rejected(api):
    """PRD §3.5: "if this would drive the value negative, the request
    is rejected with ERR_LOAN_OVERPAYMENT and no row is created."

    Claim: a repayment > outstanding -> ERR_LOAN_OVERPAYMENT.
    """
    plan, p, loan = setup_loan_lifecycle(
        target_balance_cents=4_000_000,
        requested_amount_cents=500_000,
        term_months=10,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    headers = make_participant_headers(p["id"])
    res = api.create_loan_repayment(
        plan["id"], p["id"], loan["id"],
        create_loan_repayment_payload(payment_amount_cents=500_001),
        headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_LOAN_OVERPAYMENT.value,
        expected_status=422,
    )


# ===========================================================================
# Full repayment -> SATISFIED (PRD §3.5)
# ===========================================================================
def test_full_repayment_transitions_loan_to_satisfied(api):
    """PRD §3.5: "When outstanding_principal_cents reaches exactly
    zero after this repayment, the loan transitions automatically
    from ACTIVE to SATISFIED (which is terminal) in the same commit."

    Claim: after 10 even repayments of 100k each on a 1M / 10-month
    loan, the loan reaches SATISFIED with outstanding == 0.

    # difficulty: non_linear_state_machine/loan_branching_on_default_vs_satisfied
    """
    plan, p, loan = setup_loan_lifecycle(
        target_balance_cents=4_000_000,
        requested_amount_cents=1_000_000,
        term_months=10,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    for _ in range(10):
        post_loan_repayment(
            plan["id"], p["id"], loan["id"],
            payment_amount_cents=100_000,
        )
    loan_after = validate_success(
        api.get_loan(
            plan["id"], p["id"], loan["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    assert loan_after["outstanding_principal_cents"] == 0
    assert loan_after["status"] == "SATISFIED"


# ===========================================================================
# Rounding remainder — PRD §3.5
# ===========================================================================
def test_loan_last_installment_absorbs_remainder(api):
    """PRD §3.5: "Because of rounding, the sum of term_months equal
    payments may differ from approved_amount_cents by up to a few
    cents; the last installment absorbs the rounding remainder so
    that the total of all payments equals approved_amount_cents
    exactly."

    Claim: approved=1_000_000, term=12 -> monthly = round_half_up(83333.33)
    = 83333. After 11 repayments of 83333 (=916663), outstanding ==
    83337. The 12th repayment of 83337 drives outstanding to 0 and
    flips status to SATISFIED. A 12th repayment of 83338 would be
    ERR_LOAN_OVERPAYMENT.

    # difficulty: combinatorial_formula/monthly_payment_rounding_remainder_on_last_installment
    """
    plan, p, loan = setup_loan_lifecycle(
        target_balance_cents=4_000_000,
        requested_amount_cents=1_000_000,
        term_months=12,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    assert loan["monthly_payment_cents"] == 83_333
    for _ in range(11):
        post_loan_repayment(
            plan["id"], p["id"], loan["id"],
            payment_amount_cents=83_333,
        )
    loan_mid = validate_success(
        api.get_loan(
            plan["id"], p["id"], loan["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    assert loan_mid["outstanding_principal_cents"] == 83_337
    assert loan_mid["status"] == "ACTIVE"
    # 12th repayment of 83337 -> SATISFIED.
    post_loan_repayment(
        plan["id"], p["id"], loan["id"],
        payment_amount_cents=83_337,
    )
    loan_end = validate_success(
        api.get_loan(
            plan["id"], p["id"], loan["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    assert loan_end["outstanding_principal_cents"] == 0
    assert loan_end["status"] == "SATISFIED"


def test_loan_last_installment_overpayment_rejected(api):
    """PRD §3.5: "if this would drive the value negative, the request
    is rejected with ERR_LOAN_OVERPAYMENT".

    Claim: a 12th repayment of 83338 (one cent above the rounding-
    remainder amount of 83337) -> ERR_LOAN_OVERPAYMENT.

    # difficulty: combinatorial_formula/monthly_payment_rounding_remainder_on_last_installment
    """
    plan, p, loan = setup_loan_lifecycle(
        target_balance_cents=4_000_000,
        requested_amount_cents=1_000_000,
        term_months=12,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    for _ in range(11):
        post_loan_repayment(
            plan["id"], p["id"], loan["id"],
            payment_amount_cents=83_333,
        )
    headers = make_participant_headers(p["id"])
    res = api.create_loan_repayment(
        plan["id"], p["id"], loan["id"],
        create_loan_repayment_payload(payment_amount_cents=83_338),
        headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_LOAN_OVERPAYMENT.value,
        expected_status=422,
    )


# ===========================================================================
# LoanRepayment is ledger — PRD §2.4
# ===========================================================================
def test_loan_repayment_omits_updated_at_and_version(api):
    """PRD §2.4: "Three entity types are immutable ledger or audit
    rows and therefore carry only id and created_at ... LoanRepayment".

    Claim: a LoanRepayment response does NOT carry updated_at or
    version.
    """
    plan, p, loan = setup_loan_lifecycle(
        target_balance_cents=4_000_000,
        requested_amount_cents=500_000,
        term_months=10,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    rep = post_loan_repayment(
        plan["id"], p["id"], loan["id"],
        payment_amount_cents=50_000,
    )
    assert "updated_at" not in rep
    assert "version" not in rep


# ===========================================================================
# Approve required from REQUESTED — PRD §3.5
# ===========================================================================
def test_approve_active_loan_rejected_loan_not_requested(api, admin_headers):
    """PRD §3.5: "An attempt to approve a loan whose status is anything
    other than REQUESTED is rejected with ERR_LOAN_NOT_REQUESTED."

    Claim: approving a loan that is already ACTIVE ->
    ERR_LOAN_NOT_REQUESTED.
    """
    plan, p, loan = setup_loan_lifecycle(
        target_balance_cents=4_000_000,
        requested_amount_cents=200_000, term_months=10,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    res = api.approve_loan(
        plan["id"], p["id"], loan["id"], None, admin_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_LOAN_NOT_REQUESTED.value,
        expected_status=409,
    )


# ===========================================================================
# Loan-lifecycle balance conservation — PRD §3.5
# ===========================================================================
def test_loan_full_lifecycle_preserves_balance(api):
    """PRD §3.5: "the system pins approved_amount_cents to
    requested_amount_cents exactly ... outstanding_principal_cents is
    decremented by payment_amount_cents". The loan-approve step does
    NOT debit total_account_balance_cents and the repayment step does
    NOT credit it (repayments come from outside funds), so the full
    {approve -> N repayments -> SATISFIED} lifecycle leaves the
    participant's total_account_balance_cents unchanged.

    Claim: balance_after_satisfied == balance_before_request.

    # difficulty: compensating_invariant/loan_lifecycle_preserves_participant_total_balance
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=3_000_000,
        cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    p_before = validate_success(
        api.get_participant(
            plan["id"], p["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    balance_before = p_before["total_account_balance_cents"]
    loan = request_and_approve_loan(
        plan["id"], p["id"],
        requested_amount_cents=500_000, term_months=5,
    )
    # 5 * 100_000 = 500_000 exact (no rounding remainder).
    for _ in range(5):
        post_loan_repayment(
            plan["id"], p["id"], loan["id"],
            payment_amount_cents=100_000,
        )
    p_after = validate_success(
        api.get_participant(
            plan["id"], p["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    assert p_after["total_account_balance_cents"] == balance_before
    loan_now = validate_success(
        api.get_loan(
            plan["id"], p["id"], loan["id"],
            TEST_USERS["admin_headers"],
        ),
        200,
    )
    assert loan_now["status"] == "SATISFIED"
    assert loan_now["outstanding_principal_cents"] == 0


def test_loan_full_lifecycle_preserves_balance_alternate(api):
    """PRD §3.5 conservation rule — second test for the difficulty
    instance, exercised at a different scale.

    # difficulty: compensating_invariant/loan_lifecycle_preserves_participant_total_balance
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=4_000_000,
        cliff_years=1,
        starting_clock="2026-02-01", hire_date="2020-06-01",
    )
    p_before = validate_success(
        api.get_participant(
            plan["id"], p["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    balance_before = p_before["total_account_balance_cents"]
    loan = request_and_approve_loan(
        plan["id"], p["id"],
        requested_amount_cents=200_000, term_months=4,
    )
    # 4 * 50_000 = 200_000 exact.
    for _ in range(4):
        post_loan_repayment(
            plan["id"], p["id"], loan["id"],
            payment_amount_cents=50_000,
        )
    p_after = validate_success(
        api.get_participant(
            plan["id"], p["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    assert p_after["total_account_balance_cents"] == balance_before
