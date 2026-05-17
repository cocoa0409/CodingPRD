"""Disbursement lifecycle: SCHEDULED -> PAID / FAILED / CANCELED.

Coverage targets (PRD §3.3):
- create returns SCHEDULED disbursement.
- /retry on FAILED with sufficient escrow -> PAID.
- /retry on FAILED with insufficient escrow -> ERR_INSUFFICIENT_ESCROW.
- /cancel on SCHEDULED -> CANCELED.
- Clock advance past scheduled_date with sufficient escrow -> PAID
  and decrements Loan.escrow_balance_cents.
- Clock advance past scheduled_date with insufficient escrow -> FAILED
  with failure_reason=INSUFFICIENT_ESCROW.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_disbursement,
    cancel_disbursement,
    get_loan,
    iso_datetime_utc_midnight,
    retry_disbursement,
    schedule_disbursement,
    setup_borrower_and_current_loan,
    setup_loan_with_escrow_balance,
    today_utc,
    validate_error,
    validate_success,
)


class TestDisbursementCreate:
    def test_create_returns_scheduled(self, api, servicer_headers):
        """PRD §3.3: "Disbursements begin in status SCHEDULED."

        Claim: a freshly created disbursement has status=SCHEDULED.
        """
        b, loan = setup_borrower_and_current_loan()
        d = schedule_disbursement(
            loan["id"], type="PROPERTY_TAX",
            scheduled_date=iso_datetime_utc_midnight(
                today_utc() + timedelta(days=60),
            ),
            amount_cents=120_000,
        )
        assert_disbursement(d)
        assert d["status"] == "SCHEDULED"


class TestDisbursementMaturation:
    def test_clock_advance_pays_when_escrow_sufficient(
        self, api, servicer_headers,
    ):
        """PRD §3.3: "If Loan.escrow_balance_cents is at least the
        disbursement's amount_cents, the disbursement transitions to
        PAID, paid_at is stamped, and Loan.escrow_balance_cents is
        decremented by amount_cents."

        Claim: schedule disbursement -> seed escrow >= amount ->
        advance clock past scheduled_date -> disbursement is PAID and
        Loan.escrow_balance_cents drops by amount.
        """
        # Seed escrow to 200_000 cents, then schedule a 120_000
        # PROPERTY_TAX disbursement 10 days out and advance the clock.
        b, loan = setup_loan_with_escrow_balance(200_000)
        scheduled = iso_datetime_utc_midnight(
            today_utc() + timedelta(days=10),
        )
        d = schedule_disbursement(loan["id"], type="PROPERTY_TAX",
                                  scheduled_date=scheduled,
                                  amount_cents=120_000)
        pre = int(get_loan(loan["id"])["escrow_balance_cents"])
        advance_clock(11)
        # Re-read the disbursement via list endpoint.
        resp = api.list_disbursements(loan["id"], servicer_headers)
        data = validate_success(resp, expected_status=200)
        items = data if isinstance(data, list) else data.get("data", data)
        matched = next(x for x in items if x["id"] == d["id"])
        assert matched["status"] == "PAID"
        assert matched.get("paid_at"), "paid_at must be stamped"
        post = int(get_loan(loan["id"])["escrow_balance_cents"])
        assert post == pre - 120_000, (
            f"escrow_balance_cents decreased by {pre - post}, "
            f"expected 120_000"
        )

    def test_clock_advance_fails_when_escrow_insufficient(
        self, api, servicer_headers,
    ):
        """PRD §3.3: "If the balance is insufficient, the disbursement
        transitions to FAILED with failure_reason set to
        INSUFFICIENT_ESCROW".

        Claim: scheduled disbursement amount > escrow_balance ->
        FAILED with failure_reason=INSUFFICIENT_ESCROW after clock
        advances past scheduled_date.
        """
        b, loan = setup_borrower_and_current_loan()
        # escrow_balance_cents is 0 at creation.
        d = schedule_disbursement(
            loan["id"], type="HAZARD_INSURANCE",
            scheduled_date=iso_datetime_utc_midnight(
                today_utc() + timedelta(days=10),
            ),
            amount_cents=120_000,
        )
        advance_clock(11)
        resp = api.list_disbursements(loan["id"], servicer_headers)
        data = validate_success(resp, expected_status=200)
        items = data if isinstance(data, list) else data.get("data", data)
        matched = next(x for x in items if x["id"] == d["id"])
        assert matched["status"] == "FAILED"
        assert matched["failure_reason"] == "INSUFFICIENT_ESCROW"


class TestDisbursementRetry:
    def test_retry_on_failed_with_insufficient_escrow_rejected(
        self, api, servicer_headers,
    ):
        """PRD §3.3: "A Servicer may retry a FAILED disbursement at any
        later time — the retry succeeds (transitioning the disbursement
        to PAID ...) only when escrow once again has sufficient funds;
        otherwise the retry is rejected with ERR_INSUFFICIENT_ESCROW."

        Claim: /retry on a FAILED disbursement when escrow is still
        insufficient -> ERR_INSUFFICIENT_ESCROW.
        """
        b, loan = setup_borrower_and_current_loan()
        d = schedule_disbursement(
            loan["id"], type="PROPERTY_TAX",
            scheduled_date=iso_datetime_utc_midnight(
                today_utc() + timedelta(days=10),
            ),
            amount_cents=120_000,
        )
        advance_clock(11)
        # Escrow still 0; retry must fail with ERR_INSUFFICIENT_ESCROW.
        resp = api.retry_disbursement(loan["id"], d["id"],
                                      servicer_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ESCROW.value)


class TestDisbursementCancel:
    def test_cancel_scheduled_transitions_to_canceled(
        self, api, servicer_headers,
    ):
        """PRD §3.3: "A Servicer may also cancel any SCHEDULED
        disbursement; cancellation transitions the disbursement to
        CANCELED."

        Claim: /cancel on a SCHEDULED disbursement -> status=CANCELED.
        """
        b, loan = setup_borrower_and_current_loan()
        d = schedule_disbursement(
            loan["id"], type="PROPERTY_TAX",
            scheduled_date=iso_datetime_utc_midnight(
                today_utc() + timedelta(days=60),
            ),
            amount_cents=120_000,
        )
        d_cancel = cancel_disbursement(loan["id"], d["id"])
        assert d_cancel["status"] == "CANCELED"
