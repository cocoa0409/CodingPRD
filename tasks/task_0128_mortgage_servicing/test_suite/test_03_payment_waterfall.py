"""Payment posting, waterfall allocation, reversal.

Coverage targets (PRD §3.2):
- POST /payments rejects amount_cents <= 0 with ERR_PAYMENT_AMOUNT_INVALID.
- Payment created with status=POSTED on success.
- Waterfall: late_fee -> interest -> principal -> escrow -> suspense.
- Posting decrements principal_balance_cents and increments
  escrow_balance_cents per allocations.
- next_due_date advances one month per FULLY satisfied installment.
- Reversal restores principal, escrow, and rolls next_due_date back.
- Reversing a non-POSTED payment -> ERR_INVALID_STATE.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    ApiErrorId,
    LATE_FEE_PER_MONTH_CENTS,
    advance_clock,
    assert_payment,
    assert_principal_invariant,
    create_payment_payload,
    get_loan,
    iso_datetime_utc_midnight,
    post_payment,
    reverse_payment,
    setup_borrower_and_current_loan,
    setup_loan_at_delinquency_days,
    today_utc,
    validate_error,
    validate_success,
)


class TestPaymentAmountValidation:
    """PRD §3.2 / validations[priority=25]."""

    @pytest.mark.parametrize("bad_amount", [0, -1, -100_000])
    def test_zero_or_negative_amount_rejected(
        self, api, servicer_headers, bad_amount,
    ):
        """PRD §3.2: "amount_cents (which must be strictly positive —
        otherwise the request is rejected with ERR_PAYMENT_AMOUNT_INVALID)".

        Claim: amount_cents <= 0 -> ERR_PAYMENT_AMOUNT_INVALID / 422.
        """
        b, loan = setup_borrower_and_current_loan()
        resp = api.create_payment(
            loan["id"],
            create_payment_payload(
                received_date=iso_datetime_utc_midnight(today_utc()),
                amount_cents=bad_amount,
            ),
            servicer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID.value)


class TestPaymentWaterfallSimple:
    """PRD §3.2 simple posting and balance updates."""

    def test_post_payment_creates_posted_record(self, api, servicer_headers):
        """PRD §3.2: "Each accepted payment is recorded with status
        POSTED".

        Claim: a successful POST /payments returns status=POSTED.
        """
        b, loan = setup_borrower_and_current_loan()
        # Advance one installment so there's past-due P&I to allocate.
        advance_clock(30)
        sched = int(loan["scheduled_payment_cents"])
        p = post_payment(loan["id"], amount_cents=sched)
        assert_payment(p)
        assert p["status"] == "POSTED"
        assert p["amount_cents"] == sched

    def test_principal_balance_decremented_by_allocation(
        self, api, servicer_headers,
    ):
        """PRD §3.2: "Loan.principal_balance_cents is decremented by
        allocation_principal_cents".

        Claim: after a payment that allocates k cents to principal,
        Loan.principal_balance_cents = pre_balance - k.
        """
        b, loan = setup_borrower_and_current_loan()
        pre_principal = loan["principal_balance_cents"]
        advance_clock(30)
        sched = int(loan["scheduled_payment_cents"])
        p = post_payment(loan["id"], amount_cents=sched)
        post_loan = get_loan(loan["id"])
        delta = pre_principal - post_loan["principal_balance_cents"]
        assert delta == p["allocation_principal_cents"], (
            f"principal_balance decreased by {delta}, expected "
            f"{p['allocation_principal_cents']} (the allocation)"
        )

    def test_late_fee_allocated_before_interest_on_delinquent(
        self, api,
    ):
        """PRD §3.2: "outstanding late fees (where late fees accrue at
        five thousand cents per late month — that is fifty dollars —
        capped at twenty-five thousand cents, computed as the
        integer-floor of delinquency_days divided by 30, multiplied by
        the per-month late fee, capped at the cap); then accrued
        interest on past-due principal and interest installments".

        Claim: on a loan at delinquency_days=35 (1 late month), the
        first allocation bucket from a small payment that fits inside
        the late-fee demand is allocation_late_fee_cents == 5000;
        further buckets are 0.
        """
        b, loan = setup_loan_at_delinquency_days(35)
        # Post exactly 5000 cents — fits inside the 1 month of late fees.
        p = post_payment(loan["id"], amount_cents=LATE_FEE_PER_MONTH_CENTS)
        assert p["allocation_late_fee_cents"] == LATE_FEE_PER_MONTH_CENTS
        assert p["allocation_interest_cents"] == 0
        assert p["allocation_principal_cents"] == 0
        assert p["allocation_escrow_cents"] == 0
        assert p["allocation_suspense_cents"] == 0


class TestPaymentReverse:
    """PRD §3.2 reversal lifecycle."""

    def test_reverse_posted_payment_sets_reversed(
        self, api, servicer_headers,
    ):
        """PRD §3.2: "On reversal, Payment.status becomes REVERSED,
        reversed_at is stamped to now".

        Claim: reversing a POSTED payment marks status=REVERSED with
        a non-null reversed_at.
        """
        b, loan = setup_borrower_and_current_loan()
        advance_clock(30)
        p = post_payment(loan["id"],
                         amount_cents=int(loan["scheduled_payment_cents"]))
        rev = reverse_payment(loan["id"], p["id"])
        assert rev["status"] == "REVERSED"
        assert isinstance(rev.get("reversed_at"), str)

    def test_reverse_restores_principal_balance(
        self, api, servicer_headers,
    ):
        """PRD §3.2: "Loan.principal_balance_cents is incremented back
        by allocation_principal_cents".

        Claim: principal_balance_cents after reverse == principal_balance
        before posting.
        """
        b, loan = setup_borrower_and_current_loan()
        pre = loan["principal_balance_cents"]
        advance_clock(30)
        p = post_payment(loan["id"],
                         amount_cents=int(loan["scheduled_payment_cents"]))
        reverse_payment(loan["id"], p["id"])
        loan2 = get_loan(loan["id"])
        assert loan2["principal_balance_cents"] == pre, (
            f"after reversal, principal_balance should equal {pre}, "
            f"got {loan2['principal_balance_cents']}"
        )

    def test_reverse_already_reversed_payment_rejected(
        self, api, servicer_headers,
    ):
        """PRD §3.2: "Reversal is only permitted ... only against a
        payment whose status is still POSTED; otherwise the attempt is
        rejected with ERR_INVALID_STATE."

        Claim: reversing a REVERSED payment -> ERR_INVALID_STATE.
        """
        b, loan = setup_borrower_and_current_loan()
        advance_clock(30)
        p = post_payment(loan["id"],
                         amount_cents=int(loan["scheduled_payment_cents"]))
        reverse_payment(loan["id"], p["id"])
        resp = api.reverse_payment(loan["id"], p["id"],
                                   servicer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestPrincipalInvariant:
    """PRD §3.2 conservation invariant."""

    def test_principal_conservation_after_post_and_reverse(
        self, api, servicer_headers,
    ):
        """PRD §3.2: "The fundamental invariant preserved across
        posting and reversal is that the current principal_balance_cents
        plus the sum of allocation_principal_cents across all POSTED
        payments equals original_principal_cents minus any principal
        forbearance granted by an accepted loan modification."

        Claim: invariant holds at three timestamps: pre-post, post-post,
        post-reverse.
        """
        b, loan = setup_borrower_and_current_loan()
        assert_principal_invariant(loan, posted_payments=[])
        advance_clock(30)
        p = post_payment(loan["id"],
                         amount_cents=int(loan["scheduled_payment_cents"]))
        loan2 = get_loan(loan["id"])
        # Only one POSTED payment exists.
        assert_principal_invariant(loan2, posted_payments=[p])
        # Now reverse it; p is no longer in the POSTED set.
        reverse_payment(loan["id"], p["id"])
        loan3 = get_loan(loan["id"])
        assert_principal_invariant(loan3, posted_payments=[])
