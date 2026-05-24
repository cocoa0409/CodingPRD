"""Payment posting, the allocation waterfall (fees/interest/principal),
reversal window, and the post-then-reverse compensating invariant.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    assert_payment,
    create_payment_payload,
    TEST_USERS,
    advance_clock, create_borrower, create_loan, fire_servicing_event,
    get_loan_version, get_loan,
    create_loan_in_repayment,
    attach_standard_10yr_plan,
    setup_loan_in_repayment_with_standard_plan,
    setup_loan_in_default,
)


# ─── Boundary precision: backdate window (Difficulty Rule 6b) ──


def test_payment_backdate_15_days_passes_at_boundary(api, servicer_headers):
    """PRD §3.4: "A payment may be back-dated by up to fifteen days:
    `posted_on` must be no earlier than the clock date minus fifteen days
    (so a `posted_on` exactly fifteen days earlier than the clock is
    accepted; sixteen days earlier is rejected with
    `ERR_PAYMENT_DATE_OUT_OF_WINDOW`)."

    Design: Difficulty/boundary_precision_check/payment_backdate_window_15_day_half_open_boundary
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        original_principal_cents=2_000_000, interest_rate_bps=533,
    )
    attach_standard_10yr_plan(loan["id"])
    advance_clock("2026-07-01T00:00:00Z")
    # posted_on exactly 15 days before the clock — accepted.
    res = api.create_payment(
        create_payment_payload(loan["id"], 100, "2026-06-16", "ACH"),
        servicer_headers,
    )
    payment = validate_success(res, 201)
    assert payment["status"] == "POSTED"


def test_payment_backdate_16_days_fails_at_boundary(api, servicer_headers):
    """PRD §3.4: "A payment may be back-dated by up to fifteen days:
    `posted_on` must be no earlier than the clock date minus fifteen days
    (so a `posted_on` exactly fifteen days earlier than the clock is
    accepted; sixteen days earlier is rejected with
    `ERR_PAYMENT_DATE_OUT_OF_WINDOW`)."

    Design: Difficulty/boundary_precision_check/payment_backdate_window_15_day_half_open_boundary
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        original_principal_cents=2_000_000, interest_rate_bps=533,
    )
    attach_standard_10yr_plan(loan["id"])
    advance_clock("2026-07-01T00:00:00Z")
    # posted_on 16 days before the clock — rejected.
    res = api.create_payment(
        create_payment_payload(loan["id"], 100, "2026-06-15", "ACH"),
        servicer_headers,
    )
    validate_error(res, "ERR_PAYMENT_DATE_OUT_OF_WINDOW", expected_status=422)


# ─── Allocation waterfall (corner) ──────────────────


def test_payment_allocation_no_fees_no_accrued_interest_all_principal(api, servicer_headers):
    """PRD §3.4: "The second bucket is accrued interest: from whatever
    remains, the system applies the smaller of the remaining amount and
    the loan's current `accrued_interest_cents`, and decrements
    `accrued_interest_cents` by that figure. The third bucket is
    outstanding principal: from whatever still remains, the system applies
    the smaller of the remaining amount and the loan's current
    `outstanding_principal_cents`, and decrements
    `outstanding_principal_cents` accordingly."

    On a 0%-rate, REPAYMENT loan with no accrued interest and no DEFAULT
    state, a payment of 10000 cents allocates entirely to principal
    (fees and interest buckets are both zero).

    Design: Corner/calculations/payment_allocation_waterfall_interest_first_then_principal
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        original_principal_cents=15_000, interest_rate_bps=0,
    )
    attach_standard_10yr_plan(loan["id"])
    res = api.create_payment(
        create_payment_payload(loan["id"], 10_000, "2026-06-01", "ACH"),
        servicer_headers,
    )
    payment = validate_success(res, 201)
    assert payment["applied_to_fees_cents"] == 0
    assert payment["applied_to_interest_cents"] == 0
    assert payment["applied_to_principal_cents"] == 10_000

    loan_after = get_loan(loan["id"])
    assert loan_after["outstanding_principal_cents"] == 5_000


def test_treasury_offset_collection_fee_applied_on_default_loan(api, servicer_headers):
    """PRD §3.4: "The first bucket is collection fees, and it is non-zero
    only for the narrow combination of a loan in `DEFAULT` paying via
    `TREASURY_OFFSET`: in that case the statutory collection fee is
    computed as the floor of the gross `amount_cents` multiplied by 0.1825
    (that is, 18.25 percent of the gross amount, computed once per payment
    rather than per bucket and rounded down to a whole cent); the fee
    bucket then takes the lesser of the remaining amount and that floor."

    Payment of 100000 cents via TREASURY_OFFSET on a DEFAULT loan with
    200000 principal and zero accrued interest: floor(100000 * 0.1825) =
    18250 fees, then 0 interest, then 81750 principal.

    Design: Corner/calculations/treasury_offset_collection_fee_applied_on_default_loan
    """
    _, loan = setup_loan_in_default(
        clock_initial="2026-06-01T00:00:00Z",
        disbursement_date="2025-06-01",
        grace_begin_on="2025-06-01",
        repayment_begin_on="2026-06-01",
        advance_to="2027-03-28T00:00:00Z",
        original_principal_cents=200_000,
        interest_rate_bps=0,
    )
    assert loan["status"] == "DEFAULT"
    res = api.create_payment(
        create_payment_payload(loan["id"], 100_000, "2027-03-28", "TREASURY_OFFSET"),
        servicer_headers,
    )
    payment = validate_success(res, 201)
    assert payment["applied_to_fees_cents"] == 18_250
    assert payment["applied_to_interest_cents"] == 0
    assert payment["applied_to_principal_cents"] == 81_750


def test_ach_payment_on_default_loan_no_collection_fee(api, servicer_headers):
    """PRD §3.4: "The first bucket is collection fees, and it is non-zero
    only for the narrow combination of a loan in `DEFAULT` paying via
    `TREASURY_OFFSET`: in that case the statutory collection fee is
    computed as the floor of the gross `amount_cents` multiplied by 0.1825
    (that is, 18.25 percent of the gross amount, computed once per payment
    rather than per bucket and rounded down to a whole cent); the fee
    bucket then takes the lesser of the remaining amount and that floor.
    For every other combination, the fee bucket is zero."

    Payment of 50000 cents via ACH on a DEFAULT loan: zero fees, all
    50000 cents to principal (no accrued interest on this 0%-rate loan).

    Design: Corner/calculations/ach_payment_on_default_no_collection_fee
    """
    _, loan = setup_loan_in_default(
        clock_initial="2026-06-01T00:00:00Z",
        disbursement_date="2025-06-01",
        grace_begin_on="2025-06-01",
        repayment_begin_on="2026-06-01",
        advance_to="2027-03-28T00:00:00Z",
        original_principal_cents=200_000,
        interest_rate_bps=0,
    )
    assert loan["status"] == "DEFAULT"
    res = api.create_payment(
        create_payment_payload(loan["id"], 50_000, "2027-03-28", "ACH"),
        servicer_headers,
    )
    payment = validate_success(res, 201)
    assert payment["applied_to_fees_cents"] == 0
    assert payment["applied_to_principal_cents"] == 50_000


# ─── Compensating invariant: post-then-reverse balance ──


def test_payment_post_then_reverse_restores_balances(api, servicer_headers):
    """PRD §3.4: "On success the payment moves to `REVERSED`,
    `outstanding_principal_cents` is increased by the prior
    `applied_to_principal_cents`, `accrued_interest_cents` is increased by
    the prior `applied_to_interest_cents`, the loan's `version` increments,
    and the borrower's `PSLFTracker` is recounted..."

    A 50000-cent payment posted then reversed must leave
    outstanding_principal_cents and accrued_interest_cents at their
    pre-payment values.

    Design: Difficulty/compensating_invariant/payment_post_then_reverse_preserves_total_balance_cents
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        original_principal_cents=2_000_000,
        interest_rate_bps=0,
        disbursement_date="2026-06-01",
        grace_begin_on="2026-06-01",
    )
    attach_standard_10yr_plan(loan["id"])

    before = get_loan(loan["id"])
    pay_res = api.create_payment(
        create_payment_payload(loan["id"], 50_000, "2026-06-01", "ACH"),
        servicer_headers,
    )
    payment = validate_success(pay_res, 201)
    assert payment["applied_to_principal_cents"] == 50_000

    rev = api.reverse_payment(payment["id"], servicer_headers)
    reversed_payment = validate_success(rev, 200)
    assert reversed_payment["status"] == "REVERSED"

    after = get_loan(loan["id"])
    assert after["outstanding_principal_cents"] == before["outstanding_principal_cents"], (
        "Reversal must restore outstanding_principal_cents to its pre-post value"
    )
    assert after["accrued_interest_cents"] == before["accrued_interest_cents"], (
        "Reversal must restore accrued_interest_cents to its pre-post value"
    )


def test_payment_post_then_reverse_marks_reversed_status(api, servicer_headers):
    """PRD §3.4: "On success the payment moves to `REVERSED`..."
    PRD §3.4: "The reversal endpoint requires the payment to be in
    `POSTED` status and its `posted_on` to be no earlier than the
    simulation clock date minus thirty days..."

    The compensating invariant also requires the Payment.status to
    transition POSTED → REVERSED on the reversal — a step that's a
    necessary precondition for the balance restoration the invariant
    asserts.

    Design: Difficulty/compensating_invariant/payment_post_then_reverse_preserves_total_balance_cents
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        original_principal_cents=2_000_000,
        interest_rate_bps=0,
        disbursement_date="2026-06-01",
        grace_begin_on="2026-06-01",
    )
    attach_standard_10yr_plan(loan["id"])
    pay = validate_success(api.create_payment(
        create_payment_payload(loan["id"], 50_000, "2026-06-01", "ACH"),
        servicer_headers,
    ), 201)
    assert pay["status"] == "POSTED"
    rev = validate_success(api.reverse_payment(pay["id"], servicer_headers), 200)
    assert rev["status"] == "REVERSED"
    # And the Payment is now observable as REVERSED via GET.
    pay_after = validate_success(api.get_payment(pay["id"], servicer_headers), 200)
    assert pay_after["status"] == "REVERSED"


def test_payment_reverse_window_exceeded_returns_invalid_state(api, servicer_headers):
    """PRD §3.4: "A `LoanServicer` may reverse a previously posted payment
    for up to thirty days after its `posted_on`. The reversal endpoint
    requires the payment to be in `POSTED` status and its `posted_on` to
    be no earlier than the simulation clock date minus thirty days;
    otherwise it is rejected with `ERR_INVALID_STATE`."

    A payment posted on 2026-06-01 cannot be reversed on 2026-07-15
    (44 days later).

    Design: Corner/state_machines/payment_pending_to_reversed_is_invalid
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        original_principal_cents=200_000, interest_rate_bps=0,
    )
    attach_standard_10yr_plan(loan["id"])
    pay = validate_success(api.create_payment(
        create_payment_payload(loan["id"], 10_000, "2026-06-01", "ACH"),
        servicer_headers,
    ), 201)
    advance_clock("2026-07-15T00:00:00Z")
    res = api.reverse_payment(pay["id"], servicer_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    # Payment status remains POSTED — failed reversal did not move it.
    pay_after = validate_success(api.get_payment(pay["id"], servicer_headers), 200)
    assert pay_after["status"] == "POSTED"


# ─── ERR_PAYMENT_EXCEEDS_BALANCE (corner) ───────────


def test_payment_amount_exceeds_balance_returns_invalid(api, servicer_headers):
    """PRD §3.4: "If non-zero residue remains after fees, interest, and
    principal are exhausted and the loan is not paid off, the request is
    rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. The boundary is strict: a
    payment whose `amount_cents` equals the sum of fees-due, current
    interest, and current principal succeeds (full payoff); a payment one
    cent above that sum fails."

    Design: Corner/errors/error_payment_exceeds_balance_triggered
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        original_principal_cents=10_000, interest_rate_bps=0,
    )
    attach_standard_10yr_plan(loan["id"])
    res = api.create_payment(
        create_payment_payload(loan["id"], 20_000, "2026-06-01", "ACH"),
        servicer_headers,
    )
    validate_error(res, "ERR_PAYMENT_EXCEEDS_BALANCE", expected_status=422)


# ─── List payments filter (corner) ──────────────────


def test_list_payments_filter_by_loan_id(api, servicer_headers):
    """PRD §4 (endpoint table for GET /v1/payments): "List Payments
    (filterable by `loan_id` and `status`; paginated)."

    Design: Corner/endpoints/list_payments_filter_by_loan_id
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="filter-payments@example.com")
    loan_a = create_loan(borrower["id"], original_principal_cents=100_000,
                          interest_rate_bps=0, disbursement_date="2026-06-01")
    loan_b = create_loan(borrower["id"], original_principal_cents=200_000,
                          interest_rate_bps=0, disbursement_date="2026-06-01")
    for L in (loan_a, loan_b):
        fire_servicing_event(L["id"], "GRACE_BEGIN", "2026-06-01", "OTHER")
        fire_servicing_event(L["id"], "REPAYMENT_BEGIN", "2026-06-01", "GRACE_EXPIRY")
        attach_standard_10yr_plan(L["id"])
    validate_success(api.create_payment(
        create_payment_payload(loan_a["id"], 1_000, "2026-06-01", "ACH"),
        servicer_headers,
    ), 201)
    validate_success(api.create_payment(
        create_payment_payload(loan_b["id"], 2_000, "2026-06-01", "ACH"),
        servicer_headers,
    ), 201)

    res = api.list_payments(servicer_headers, params={"loan_id": loan_a["id"]})
    assert res.status_code == 200
    body = res.json()
    data = body["data"]
    assert len(data) == 1
    assert data[0]["loan_id"] == loan_a["id"]
    assert data[0]["amount_cents"] == 1_000


# ─── Immediate-consistency (corner) ─────────────────


def test_payment_immediate_consistency_reflects_in_loan_get(api, servicer_headers):
    """PRD §3.4: "The third bucket is outstanding principal: from whatever
    still remains, the system applies the smaller of the remaining amount
    and the loan's current `outstanding_principal_cents`, and decrements
    `outstanding_principal_cents` accordingly."
    PRD §2.8: "Every cascade is treated as a true write on the touched
    resource: it refreshes `updated_at`, increments `version`, and is
    observable through subsequent reads."

    A 25000-cent payment on a 100000-principal loan immediately reduces
    outstanding_principal_cents to 75000, both on the payment response and
    on a subsequent GET /v1/loans/{loan_id}.

    Design: Corner/consistency_model/immediate_consistency_payment_reflects_in_loan_balance_same_request
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        original_principal_cents=100_000, interest_rate_bps=0,
    )
    attach_standard_10yr_plan(loan["id"])
    pay_res = api.create_payment(
        create_payment_payload(loan["id"], 25_000, "2026-06-01", "ACH"),
        servicer_headers,
    )
    payment = validate_success(pay_res, 201)
    assert payment["applied_to_principal_cents"] == 25_000

    loan_after = get_loan(loan["id"])
    assert loan_after["outstanding_principal_cents"] == 75_000
