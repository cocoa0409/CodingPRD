"""Quarterly estimated tax payments + virtual clock.

Coverage targets (PRD §3.10, §2.9):
- POST /estimated-payments creates SCHEDULED with future pay-date.
- Same-day / past pay-date -> ERR_PAYMENT_DATE_PAST.
- Cancel before pay-date succeeds.
- Cancel at or after pay-date -> ERR_PAYMENT_CANNOT_CANCEL.
- Clock advance auto-confirms payments whose pay-date is reached
  for an ACTIVE taxpayer (PRD §2.9).
- Clock advance response enumerates fired transitions.
"""
from __future__ import annotations

from datetime import date

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_clock_advance_response,
    assert_estimated_payment,
    cancel_payment,
    create_estimated_payment_payload,
    create_taxpayer,
    iso_date,
    iso_instant_utc,
    make_taxpayer_headers,
    schedule_payment,
    setup_for_payment_boundary,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Scheduling — PRD §3.10
# ===========================================================================
class TestSchedulePayment:

    def test_create_payment_starts_scheduled(self, api):
        """PRD §3.10: "The payment is born in SCHEDULED with null
        confirmed_at and null cancelled_at."

        Claim: a freshly created payment reports SCHEDULED, null
        confirmed_at, null cancelled_at.
        """
        # Reset clock to a known instant well before pay date.
        advance_clock_to(iso_instant_utc(2026, 1, 1, 0, 0, 0))
        taxpayer = create_taxpayer()
        payment = schedule_payment(
            taxpayer,
            tax_year=2025, quarter="Q1",
            amount_cents=100_000,
            scheduled_pay_date=iso_date(date(2026, 4, 15)),
        )
        assert_estimated_payment(payment)
        assert payment["status"] == "SCHEDULED"
        assert payment["confirmed_at"] is None
        assert payment["cancelled_at"] is None
        assert payment["amount_cents"] == 100_000
        assert payment["quarter"] == "Q1"

    def test_past_pay_date_rejected(self, api):
        """PRD §3.10: "The pay date must be strictly after the current
        virtual clock value at creation time; a same-day or past pay
        date is rejected with ERR_PAYMENT_DATE_PAST."

        Claim: scheduled_pay_date equal to clock's calendar date ->
        ERR_PAYMENT_DATE_PAST (same-day rejected).
        """
        advance_clock_to(iso_instant_utc(2026, 4, 15, 0, 0, 0))
        taxpayer = create_taxpayer()
        resp = api.create_estimated_payment(
            create_estimated_payment_payload(
                taxpayer_id=taxpayer["id"],
                tax_year=2025, quarter="Q2",
                amount_cents=50_000,
                scheduled_pay_date=iso_date(date(2026, 4, 15)),
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_DATE_PAST.value)


# ===========================================================================
# Cancel — PRD §3.10
# ===========================================================================
class TestCancelPayment:

    def test_cancel_before_pay_date_succeeds(self, api):
        """PRD §3.10: "A taxpayer may cancel a SCHEDULED payment before
        its pay date. The cancel operation requires that the current
        virtual clock is strictly less than the scheduled_pay_date".

        Claim: cancel before pay-date -> status CANCELLED with
        cancelled_at populated.
        """
        advance_clock_to(iso_instant_utc(2026, 1, 1, 0, 0, 0))
        taxpayer, payment = setup_for_payment_boundary(
            scheduled_pay_date=iso_date(date(2026, 6, 15)),
        )
        cancelled = cancel_payment(taxpayer, payment["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancelled_at"] is not None

    def test_cancel_at_or_after_pay_date_rejected(self, api):
        """PRD §3.10: "once the clock reaches 00:00 UTC of the pay
        date, cancel is no longer possible and the request is rejected
        with ERR_PAYMENT_CANNOT_CANCEL."

        Claim: cancel at exact midnight UTC of pay date ->
        ERR_PAYMENT_CANNOT_CANCEL.
        """
        advance_clock_to(iso_instant_utc(2026, 1, 1, 0, 0, 0))
        taxpayer, payment = setup_for_payment_boundary(
            scheduled_pay_date=iso_date(date(2026, 6, 15)),
        )
        # Advance clock to exactly pay-date midnight.
        advance_clock_to(iso_instant_utc(2026, 6, 15, 0, 0, 0))
        resp = api.cancel_estimated_payment(
            payment["id"], make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_CANNOT_CANCEL.value)


# ===========================================================================
# Auto-confirm on clock advance — PRD §2.9 / §3.10
# ===========================================================================
class TestAutoConfirm:

    def test_clock_advance_auto_confirms_payment(self, api):
        """PRD §2.9: "when the virtual clock reaches or surpasses 00:00
        UTC of the payment's scheduled_pay_date, a SCHEDULED payment
        whose owning Taxpayer is still ACTIVE is transitioned to
        CONFIRMED and confirmed_at is stamped with the new clock value."

        Claim: advancing the clock to pay-date midnight transitions a
        SCHEDULED payment to CONFIRMED.
        """
        advance_clock_to(iso_instant_utc(2026, 1, 1, 0, 0, 0))
        taxpayer, payment = setup_for_payment_boundary(
            scheduled_pay_date=iso_date(date(2026, 9, 1)),
        )
        advance_clock_to(iso_instant_utc(2026, 9, 1, 0, 0, 0))
        # Re-read the payment.
        listed = api.list_estimated_payments(
            TEST_USERS["irs_adjudicator_headers"],
            params={"taxpayer_id": taxpayer["id"]},
        ).json()["data"]
        row = next(r for r in listed if r["id"] == payment["id"])
        assert row["status"] == "CONFIRMED"
        assert row["confirmed_at"] is not None

    def test_clock_advance_response_lists_transitions(self, api):
        """PRD §2.9: "The response of the advance call enumerates every
        transition that fired, listing the affected entity, its id,
        and the from/to state pair."

        Claim: the /_clock/advance response carries
        advanced_transitions with each entry having entity, id, from,
        to.
        """
        advance_clock_to(iso_instant_utc(2026, 1, 1, 0, 0, 0))
        taxpayer, payment = setup_for_payment_boundary(
            scheduled_pay_date=iso_date(date(2026, 9, 1)),
        )
        from test_helpers import clock_advance_payload
        resp = api.advance_clock(
            clock_advance_payload(
                to_iso_timestamp=iso_instant_utc(2026, 9, 1, 0, 0, 0),
            ),
            TEST_USERS["irs_adjudicator_headers"],
        )
        data = validate_success(resp)
        assert_clock_advance_response(data)
        # The transition for our payment must be present.
        ids_in_transitions = {t["id"] for t in data["advanced_transitions"]}
        assert payment["id"] in ids_in_transitions, (
            "PRD §2.9: advance response must enumerate the firing "
            "EstimatedTaxPayment transition."
        )
