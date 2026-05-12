"""Monthly billing, payments/disputes, and quality assessment.

PRD §3.9 (Monthly Billing), §3.10 (Quality Assessment).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    advance_clock_hours,
    advance_clock_to_next_month,
    assert_billing_period,
    close_billing_period,
    close_quality_assessment,
    create_billing_period,
    create_quality_assessment,
    current_period_yyyymm,
    dispute_bill_payload,
    pay_bill_payload,
    register_shelved_parcel,
    resolve_dispute_payload,
    setup_closed_period_with_bills,
    setup_period_ready_to_close,
    setup_station_with_staff,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
    write_off_payload,
)


# ===========================================================================
# Period close preconditions
# ===========================================================================
class TestPeriodClosePreconditions:
    def test_close_before_period_end_yields_period_not_ended(self, api):
        """PRD §3.9: "The current server time must be at or after
        period_end — otherwise the close is refused with
        ERR_PERIOD_NOT_ENDED (HTTP 422)."

        Claim: closing the period before period_end yields
        ERR_PERIOD_NOT_ENDED.
        """
        ctx = setup_station_with_staff()
        period_yyyymm = current_period_yyyymm()
        # Create quality assessment in DRAFT first.
        create_quality_assessment(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        # Create billing period and close it WITHOUT advancing the clock.
        create_billing_period(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        resp = api.close_billing_period(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_ENDED)

    def test_close_with_draft_quality_assessment_rejected(self, api):
        """PRD §3.9: "the QualityAssessment for the same (station_id,
        period_yyyymm) must be in status CLOSED — otherwise the close
        is refused with ERR_QUALITY_ASSESSMENT_NOT_CLOSED (HTTP 422)."

        Claim: with a DRAFT QualityAssessment, close after period_end
        still yields ERR_QUALITY_ASSESSMENT_NOT_CLOSED.
        """
        ctx = setup_station_with_staff()
        period_yyyymm = current_period_yyyymm()
        create_quality_assessment(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        create_billing_period(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        advance_clock_to_next_month(period_yyyymm)
        resp = api.close_billing_period(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_QUALITY_ASSESSMENT_NOT_CLOSED)


# ===========================================================================
# Period close: rollups and side effects
# ===========================================================================
class TestPeriodClose:
    def test_close_issues_all_draft_bills(self, api):
        """PRD §3.9: "every child bill in DRAFT flips to ISSUED with
        issued_at stamped and a PAYMENT-targeted BILL_ISSUED event
        queued per bill."

        Claim: after period close, every child Bill has status=ISSUED
        with an ISO 8601 issued_at.
        """
        ctx = setup_closed_period_with_bills(
            parcel_count=3, overdue_hours_each=1,
        )
        bills = ctx["bills"]
        assert len(bills) >= 1
        from test_helpers import is_iso8601_timestamp
        for b in bills:
            assert b["status"] == "ISSUED"
            assert is_iso8601_timestamp(b["issued_at"])


# ===========================================================================
# Payments
# ===========================================================================
class TestBillPayment:
    def test_payment_missing_idempotency_key_rejected(self, api,
                                                     payment_system_headers):
        """PRD §3.9: "A PaymentSystem posts a payment to a bill with an
        idempotency_key and an amount; a missing idempotency_key is
        refused with ERR_IDEMPOTENCY_KEY_REQUIRED."

        Claim: POST /bills/{id}/payments without idempotency_key
        yields ERR_IDEMPOTENCY_KEY_REQUIRED.
        """
        ctx = setup_closed_period_with_bills(
            parcel_count=2, overdue_hours_each=1,
        )
        bill = ctx["bills"][0]
        resp = api.pay_bill(
            bill["id"],
            pay_bill_payload(
                amount=bill["handover_fee_amount"] + bill["storage_fee_amount"],
                include_idempotency_key=False,
            ),
            payment_system_headers,
        )
        validate_error(resp, ApiErrorId.ERR_IDEMPOTENCY_KEY_REQUIRED)

    def test_payment_flips_issued_to_paid(self, api, payment_system_headers):
        """PRD §3.9: "A successful payment requires the bill's status to
        be ISSUED, requires the parent period to be in CLOSED or
        DISPUTED, and flips the bill from ISSUED to PAID with paid_at
        stamped."

        Claim: POST /bills/{id}/payments on an ISSUED bill flips it to
        PAID with a stamped paid_at.
        """
        from test_helpers import is_iso8601_timestamp
        ctx = setup_closed_period_with_bills(
            parcel_count=2, overdue_hours_each=1,
        )
        bill = ctx["bills"][0]
        total = bill["handover_fee_amount"] + bill["storage_fee_amount"]
        resp = api.pay_bill(
            bill["id"], pay_bill_payload(amount=total),
            payment_system_headers,
        )
        paid = validate_success(resp)
        assert paid["status"] == "PAID"
        assert is_iso8601_timestamp(paid["paid_at"])

    def test_replay_same_idempotency_key_returns_replay(
        self, api, payment_system_headers,
    ):
        """PRD §3.9: "Two payments with the same idempotency key on the
        same bill collapse: the second returns the original outcome
        with ERR_IDEMPOTENCY_REPLAY at HTTP 200."

        Claim: replaying the same (bill_id, idempotency_key) returns a
        response with error_id=ERR_IDEMPOTENCY_REPLAY at HTTP 200.
        """
        from test_helpers import unique_idempotency_key
        ctx = setup_closed_period_with_bills(
            parcel_count=2, overdue_hours_each=1,
        )
        bill = ctx["bills"][0]
        total = bill["handover_fee_amount"] + bill["storage_fee_amount"]
        key = unique_idempotency_key()
        first = api.pay_bill(
            bill["id"],
            pay_bill_payload(amount=total, idempotency_key=key),
            payment_system_headers,
        )
        assert first.status_code == 200
        replay = api.pay_bill(
            bill["id"],
            pay_bill_payload(amount=total, idempotency_key=key),
            payment_system_headers,
        )
        assert replay.status_code == 200
        body = replay.json()
        assert body["data"]["error_id"] == "ERR_IDEMPOTENCY_REPLAY"

    def test_second_different_key_on_paid_bill_rejected(
        self, api, payment_system_headers,
    ):
        """PRD §3.9: "Two payments with different idempotency keys
        racing on the same already-PAID bill instead surface
        ERR_BILL_ALREADY_PAID (HTTP 409) on the loser."

        Claim: after a successful payment, a second payment with a
        DIFFERENT idempotency_key on the same PAID bill yields
        ERR_BILL_ALREADY_PAID.
        """
        from test_helpers import unique_idempotency_key
        ctx = setup_closed_period_with_bills(
            parcel_count=2, overdue_hours_each=1,
        )
        bill = ctx["bills"][0]
        total = bill["handover_fee_amount"] + bill["storage_fee_amount"]
        api.pay_bill(
            bill["id"],
            pay_bill_payload(amount=total, idempotency_key=unique_idempotency_key()),
            payment_system_headers,
        )
        # Second payment with a different idempotency_key.
        resp = api.pay_bill(
            bill["id"],
            pay_bill_payload(amount=total, idempotency_key=unique_idempotency_key()),
            payment_system_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BILL_ALREADY_PAID)


# ===========================================================================
# Disputes
# ===========================================================================
class TestBillDispute:
    def test_dispute_empty_reason_rejected(self, api, recipient_headers):
        """PRD §3.9: "The dispute payload requires a non-empty reason
        — an empty reason returns ERR_DISPUTE_REASON_REQUIRED (HTTP
        422)."

        Claim: POST /bills/{id}/dispute with empty reason yields
        ERR_DISPUTE_REASON_REQUIRED.
        """
        ctx = setup_closed_period_with_bills(
            parcel_count=2, overdue_hours_each=1,
        )
        recipient_bill = next(
            (b for b in ctx["bills"] if b["payer_kind"] == "RECIPIENT"), None,
        )
        assert recipient_bill is not None
        resp = api.dispute_bill(
            recipient_bill["id"], {"reason": ""}, recipient_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_REASON_REQUIRED)

    def test_dispute_bubbles_period_to_disputed(self, api, recipient_headers):
        """PRD §3.9: "On dispute, the bill flips from ISSUED to
        DISPUTED, its dispute_reason is recorded, and the parent
        period auto-bubbles from CLOSED to DISPUTED."

        Claim: disputing an ISSUED recipient bill flips it to DISPUTED
        and the parent BillingPeriod auto-transitions to DISPUTED.
        """
        ctx = setup_closed_period_with_bills(
            parcel_count=2, overdue_hours_each=1,
        )
        recipient_bill = next(
            (b for b in ctx["bills"] if b["payer_kind"] == "RECIPIENT"), None,
        )
        assert recipient_bill is not None
        resp = api.dispute_bill(
            recipient_bill["id"], dispute_bill_payload("wrong fee"),
            recipient_headers,
        )
        disputed = validate_success(resp)
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "wrong fee"
        period = validate_success(
            api.get_billing_period(
                ctx["station"]["id"], ctx["period_yyyymm"],
                ctx["manager_headers"],
            )
        )
        assert period["status"] == "DISPUTED"


# ===========================================================================
# Handover fee aggregation
# ===========================================================================
class TestHandoverFeeAggregation:
    def test_handover_fee_amount_equals_count_times_080(self, api):
        """PRD §3.9: "For each pair of (BillingPeriod,
        courier_company_id) the system counts the parcels at the
        period's station whose shelved_at lies in the half-open
        interval [period_start, period_end) and whose terminal status
        is not REJECTED. ... That count is multiplied by the
        per-parcel handover fee of 0.80 CNY and rounded to two decimal
        places half-up; the result becomes handover_fee_amount on the
        courier-company bill."

        Claim: with 5 successfully-shelved parcels under one courier,
        the courier-company bill carries handover_fee_amount == 4.00.
        """
        ctx = setup_closed_period_with_bills(
            parcel_count=5, overdue_hours_each=0,
        )
        courier_bill = next(
            (b for b in ctx["bills"] if b["payer_kind"] == "COURIER_COMPANY"),
            None,
        )
        assert courier_bill is not None
        assert courier_bill["handover_fee_amount"] == pytest.approx(4.00, abs=0.001)
        assert courier_bill["storage_fee_amount"] == 0.0
        assert courier_bill["parcel_count"] == 5


# ===========================================================================
# Quality assessment composite
# ===========================================================================
class TestQualityAssessmentComposite:
    def test_perfect_signals_yield_composite_one(self, api):
        """PRD §3.10: "The composite_score is the weighted sum: 0.30
        multiplied by (1 - mis_shelving_rate), plus 0.30 multiplied by
        (1 - lost_parcel_rate), plus 0.20 multiplied by (1 -
        complaint_rate), plus 0.20 multiplied by
        response_timeliness_score. The composite is rounded to two
        decimal places half-up."

        Claim: with no mis-shelving, no WRONG_DELIVERY rejections, no
        disputes, and 0 reminders (so the default response_timeliness_
        score is 1.0), the closed QualityAssessment carries
        composite_score == 1.00.
        """
        # Set up a station and create a QA without any parcels.
        ctx = setup_station_with_staff()
        period_yyyymm = current_period_yyyymm()
        create_quality_assessment(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        advance_clock_to_next_month(period_yyyymm)
        closed = close_quality_assessment(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        # All four components are zero/perfect.
        assert closed["mis_shelving_rate"] == 0
        assert closed["lost_parcel_rate"] == 0
        assert closed["complaint_rate"] == 0
        # response_timeliness_score with zero reminders defaults to 1.0.
        assert closed["response_timeliness_score"] == 1.0
        assert closed["composite_score"] == 1.00

    def test_composite_one_yields_factor_one_point_zero_five(self, api):
        """PRD §3.10: "a composite of 0.95 or greater yields a factor of
        1.05; otherwise a composite of 0.85 or greater yields a factor
        of 1.00."

        Claim: composite == 1.00 -> quality_adjustment_factor == 1.05
        snapshotted at period close.
        """
        # Setup a closed period with composite 1.00.
        ctx = setup_closed_period_with_bills(
            parcel_count=2, overdue_hours_each=0,
        )
        period = ctx["billing_period"]
        # The fixture closes both QA and period, so the factor is pinned.
        assert period["quality_adjustment_factor"] == pytest.approx(1.05, abs=0.001)
