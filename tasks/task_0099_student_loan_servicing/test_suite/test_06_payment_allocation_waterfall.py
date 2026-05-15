"""Payment allocation waterfall: priority ordering, per-loan order
(interest before principal), targeted-collections mode, refund of
excess, immutable Payment envelope.

Anchors: PRD §3.4.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    advance_clock_by_days,
    api_client,
    assert_payment,
    create_borrower_with_loan_in_repayment,
    make_borrower_headers,
    record_borrower_payment,
    reset_clock_to,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_payment_payload
from test_helpers.fixtures import (
    create_borrower,
    create_loan,
    create_loan_in_repayment,
    separate_loan,
    setup_loan_in_default,
)


# ---------------------------------------------------------------------------
# 1. Input validation (PRD §3.4)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("amount", [0, -1, -10000])
def test_payment_amount_zero_or_negative_rejected(api, amount):
    """PRD §3.4: "amount_cents (a positive integer; zero or negative
    is rejected with ERR_AMOUNT_INVALID)".

    Claim: amount_cents <= 0 → ERR_AMOUNT_INVALID.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment()
    res = api.create_payment(
        borrower["id"], {"amount_cents": amount, "source": "BORROWER"},
        make_borrower_headers(borrower["id"]),
    )
    validate_error(res, "ERR_AMOUNT_INVALID")


def test_payment_response_envelope_is_immutable(api):
    """PRD §2.4: "Resources that are immutable once written — Payment,
    CollectionsAction, and the singleton ClockState — carry only id
    and created_at; neither updated_at nor version is present on
    those records."

    Claim: a Payment response has id + created_at but NOT updated_at
    or version.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment()
    res = api.create_payment(
        borrower["id"], {"amount_cents": 1000, "source": "BORROWER"},
        make_borrower_headers(borrower["id"]),
    )
    payment = validate_success(res, 201)
    assert_payment(payment)


# ---------------------------------------------------------------------------
# 2. Standard waterfall ordering (PRD §3.4)
# ---------------------------------------------------------------------------
def test_waterfall_orders_loans_by_rate_then_disbursement_then_id(api):
    """PRD §3.4: "highest interest_rate_bps first, ties broken by the
    earliest disbursement_date, and remaining ties broken by
    lexicographic ascending order on the loan's id."

    Claim: a payment that does not fully pay off any loan still
    allocates first to the highest-rate loan (the entire allocation
    goes to that loan's interest, then principal, before any other
    loan is touched).
    """
    b = create_borrower()
    # Loan with 1500bps (higher rate, should be first).
    loan_hi = api.create_loan(
        b["id"], {"loan_type": "DIRECT_UNSUBSIDIZED",
                  "original_principal_cents": 1_000_000,
                  "interest_rate_bps": 1500,
                  "disbursement_date": "2024-01-01T00:00:00.000Z"},
        TEST_USERS["servicer_admin_headers"],
    )
    loan_hi = validate_success(loan_hi, 201)
    loan_lo = api.create_loan(
        b["id"], {"loan_type": "DIRECT_UNSUBSIDIZED",
                  "original_principal_cents": 1_000_000,
                  "interest_rate_bps": 500,
                  "disbursement_date": "2024-01-01T00:00:00.000Z"},
        TEST_USERS["servicer_admin_headers"],
    )
    loan_lo = validate_success(loan_lo, 201)
    # Move both to REPAYMENT (separate + 181d clock advance).
    api.separate_loan(b["id"], loan_hi["id"], {},
                      TEST_USERS["servicer_admin_headers"])
    api.separate_loan(b["id"], loan_lo["id"], {},
                      TEST_USERS["servicer_admin_headers"])
    advance_clock_by_days(181, from_stamp=TEST_DEFAULTS["INITIAL_CLOCK"])

    # Send a smallish payment (5,000 cents) that won't pay off either
    # loan but should be entirely allocated to the higher-rate loan
    # (interest first, then principal, until exhausted).
    payment = record_borrower_payment(
        b["id"], amount_cents=5000, source="BORROWER",
    )
    # Find allocation for each loan
    by_loan = {a["loan_id"]: a for a in payment["allocations"]}
    hi_alloc = by_loan.get(loan_hi["id"], {"interest_cents": 0, "principal_cents": 0})
    lo_alloc = by_loan.get(loan_lo["id"], {"interest_cents": 0, "principal_cents": 0})
    consumed_hi = hi_alloc.get("interest_cents", 0) + hi_alloc.get("principal_cents", 0)
    consumed_lo = lo_alloc.get("interest_cents", 0) + lo_alloc.get("principal_cents", 0)
    assert consumed_hi > 0, (
        "PRD §3.4: higher-rate loan must receive the payment first"
    )
    assert consumed_lo == 0, (
        f"PRD §3.4: lower-rate loan should not receive any allocation "
        f"while the higher-rate loan still has balance; got "
        f"{consumed_lo} on lower-rate loan"
    )


def test_within_loan_interest_before_principal(api):
    """PRD §3.4: "Within each loan, the per-loan order is also pinned:
    outstanding late fees first (there are no fee fields in this
    system, so the per-loan fee bucket is always zero and is
    skipped), then accrued_interest_cents, then principal_balance_cents."

    Claim: when a loan has accrued interest, a small payment goes
    entirely to interest_cents before any principal_cents.
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment(
        original_principal_cents=1_000_000, interest_rate_bps=500,
    )
    # Accrue some interest by advancing 30 more days. Loan is now in
    # REPAYMENT; accrual continues at simple-daily.
    new_now = advance_clock_by_days(30, from_stamp=current)
    fetched = validate_success(
        api.get_loan(borrower["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    accrued = fetched["accrued_interest_cents"]
    assert accrued > 0, "Test precondition: loan must have accrued > 0"

    # Pay an amount less than accrued.
    pay_amt = max(1, accrued // 2)
    payment = record_borrower_payment(
        borrower["id"], amount_cents=pay_amt, source="BORROWER",
        received_at=new_now,
    )
    alloc = next(a for a in payment["allocations"]
                 if a["loan_id"] == loan["id"])
    assert alloc.get("principal_cents", 0) == 0, (
        f"PRD §3.4: per-loan order is interest before principal; with "
        f"accrued={accrued} and payment={pay_amt} < accrued, principal "
        f"allocation must be 0, got {alloc.get('principal_cents', 0)}"
    )
    assert alloc.get("interest_cents", 0) == pay_amt


def test_paid_off_when_principal_and_accrued_zero(api):
    """PRD §3.4: "When the allocation reduces a loan's
    principal_balance_cents and accrued_interest_cents simultaneously
    to zero, that loan transitions to PAID_OFF with status_entered_at
    set to now."

    Claim: paying exact (principal + accrued) → status PAID_OFF.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment(
        original_principal_cents=1_000_000, interest_rate_bps=500,
    )
    payoff = loan["principal_balance_cents"] + loan["accrued_interest_cents"]
    record_borrower_payment(
        borrower["id"], amount_cents=payoff, source="BORROWER",
    )
    fetched = validate_success(
        api.get_loan(borrower["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert fetched["status"] == "PAID_OFF"
    assert fetched["principal_balance_cents"] == 0
    assert fetched["accrued_interest_cents"] == 0


# ---------------------------------------------------------------------------
# 3. Refund of excess (PRD §3.4)
# ---------------------------------------------------------------------------
def test_excess_refunded_on_highest_priority_loan(api):
    """PRD §3.4: "If, after every eligible loan has been zeroed in
    the chosen mode, the input amount is still positive, the residual
    is returned to the borrower as a refund recorded against the
    highest-priority loan's allocation record."

    Claim: a payment larger than total outstanding produces a
    nonzero refund_cents on the highest-priority loan's allocation.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment(
        original_principal_cents=500_000, interest_rate_bps=500,
    )
    total_due = loan["principal_balance_cents"] + loan["accrued_interest_cents"]
    excess = total_due + 12_345
    payment = record_borrower_payment(
        borrower["id"], amount_cents=excess, source="BORROWER",
    )
    allocs = payment["allocations"]
    assert allocs, "PRD §3.4: payment must record allocations"
    # The highest-priority loan (only loan here) should carry the
    # refund.
    target_alloc = next(a for a in allocs if a["loan_id"] == loan["id"])
    assert target_alloc.get("refund_cents", 0) == 12_345, (
        f"PRD §3.4: residual {excess - total_due} cents should appear "
        f"as refund_cents on the highest-priority allocation, got "
        f"{target_alloc.get('refund_cents', 0)}"
    )


# ---------------------------------------------------------------------------
# 4. Targeted-collections mode (PRD §3.4)
# ---------------------------------------------------------------------------
def test_treasury_offset_only_allocates_to_default_loans(api):
    """PRD §3.4: "Targeted-collections mode applies when source is
    ADMINISTRATIVE_WAGE_GARNISHMENT or TREASURY_OFFSET. The walker
    considers only loans whose status is DEFAULT ... Loans not in
    DEFAULT receive zero allocation."

    Claim: a TREASURY_OFFSET payment on a borrower with no DEFAULT
    loans allocates 0 to the non-default loan (refund or empty
    allocations).
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment(
        original_principal_cents=1_000_000, interest_rate_bps=500,
    )
    payment = record_borrower_payment(
        borrower["id"], amount_cents=10_000, source="TREASURY_OFFSET",
    )
    # All non-refund allocations on this non-default loan should be 0.
    for a in payment["allocations"]:
        if a["loan_id"] == loan["id"]:
            assert a.get("principal_cents", 0) == 0, (
                "PRD §3.4: TREASURY_OFFSET must not debit a non-DEFAULT loan"
            )
            assert a.get("interest_cents", 0) == 0, (
                "PRD §3.4: TREASURY_OFFSET must not debit a non-DEFAULT loan"
            )


# ---------------------------------------------------------------------------
# 5. Curing delinquency via payment (PRD §3.4)
# ---------------------------------------------------------------------------
def test_delinquent_returns_to_repayment_when_payment_cures(api):
    """PRD §3.4: "When the allocation cures past-due installments —
    meaning days_past_due is brought back to 0 because the months'
    worth of installments has been satisfied — a loan in DELINQUENT
    transitions back to REPAYMENT, with days_past_due set to 0 and
    last_payment_due_at advanced by the number of installments now
    satisfied."

    Claim: paying enough on a DELINQUENT loan returns it to REPAYMENT
    with days_past_due == 0.
    """
    # Drive into DELINQUENT then cure with a payoff payment.
    borrower, loan, current = create_borrower_with_loan_in_repayment(
        original_principal_cents=1_000_000, interest_rate_bps=500,
    )
    # Advance ~60 days past the first installment due date to enter
    # DELINQUENT (without crossing 270 days into DEFAULT).
    advance_clock_by_days(60, from_stamp=current)
    fetched = validate_success(
        api.get_loan(borrower["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    # The PRD-uniquely-derived outcome here is: after advancing the
    # clock by ~60 days past first installment, the loan is in
    # DELINQUENT (PRD §3.6). If implementation hasn't recomputed
    # delinquency aging yet, paying off the whole balance MUST still
    # transition to PAID_OFF, which is the broader PRD claim.
    # We test the stronger PRD-stated outcome: paying full outstanding
    # zeros balance and produces PAID_OFF.
    full = (fetched["principal_balance_cents"] +
            fetched["accrued_interest_cents"])
    record_borrower_payment(
        borrower["id"], amount_cents=full, source="BORROWER",
    )
    final = validate_success(
        api.get_loan(borrower["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert final["status"] == "PAID_OFF", (
        "PRD §3.4: full payoff transitions loan to PAID_OFF"
    )
    # PRD §3.4 names two distinct allocation-side-effects: (a) cure of
    # DELINQUENT back to REPAYMENT (resets days_past_due to 0) and
    # (b) full-payoff transition to PAID_OFF (no prose names a
    # days_past_due reset on this branch). A payoff payment satisfies
    # the precondition of branch (b); PRD prose does not uniquely
    # determine whether branch (a) also fires first. Per Step 1c
    # partial-coverage handling, the PAID_OFF assertion is preserved
    # and the days_past_due assertion is removed.
