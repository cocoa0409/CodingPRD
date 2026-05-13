"""Deposit payment, start-live, end-live, cancel, refund — the live lifecycle.

PRD §3.6 — broadcast execution; §3.7 — cancel/refund; §3.8 — settlement arming.
"""

import pytest
from datetime import datetime, timedelta, timezone

from test_helpers import (
    validate_success,
    validate_error,
    ADMIN_HEADERS,
    OPS_HEADERS,
    make_streamer_headers,
    set_clock,
    DEFAULT_BASE_TIME,
    setup_scheduled_application,
    setup_draft_application,
    attach_compatible_product,
    submit_application,
    ops_approve,
    compliance_approve,
    fetch_invoice,
    fetch_application,
    pay_deposit,
    go_live,
    end_live,
    cancel_payload,
    emit_event_payload,
    iso,
    ERR_DEPOSIT_UNPAID,
    ERR_INVALID_STATE,
    ERR_TOO_LATE_TO_CANCEL,
    ERR_REASON_REQUIRED,
)
from test_helpers.fixtures import _parse_iso


class TestDepositPaymentEvent:
    """PRD §3.6: 'Once the invoice exists in status ISSUED, the deposit must be
    paid through an externally sourced payment event...'
    """

    def test_deposit_event_transitions_invoice_and_sets_flag(self, api):
        """PRD §3.6: "On a successful match the invoice transitions from ISSUED
        to DEPOSIT_PAID and the application's deposit_paid is set to true."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application(pay_deposit_event=False)
        app = bundle["application"]
        invoice = bundle["invoice"]
        assert invoice["status"] == "ISSUED"
        pay_deposit(app, invoice)
        invoice2 = fetch_invoice(app["id"])
        assert invoice2["status"] == "DEPOSIT_PAID"
        app2 = fetch_application(app["id"])
        assert app2["deposit_paid"] is True


class TestStartLive:
    """PRD §3.6: 'Starting the broadcast transitions operational_status from
    SCHEDULED to LIVE.'
    """

    def test_start_live_happy_path(self, api):
        """PRD §3.6: "Starting the broadcast transitions operational_status from
        SCHEDULED to LIVE."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        result = go_live(streamer, app)
        assert result["operational_status"] == "LIVE"

    def test_start_live_without_deposit_returns_deposit_unpaid(self, api):
        """# difficulty: cross_entity_state_dependency/start_live_requires_invoice_deposit_paid_pair_application_invoice
        PRD §3.6: "the invoice must be in status DEPOSIT_PAID or SETTLED
        (equivalently deposit_paid must be true; otherwise ERR_DEPOSIT_UNPAID,
        HTTP 422)..."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application(pay_deposit_event=False)
        streamer = bundle["streamer"]
        app = bundle["application"]
        # Advance clock to starts_at but skip deposit
        set_clock(_parse_iso(app["starts_at"]))
        resp = api.start_live(app["id"], make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_DEPOSIT_UNPAID, expected_status=422)

    def test_start_live_before_starts_at_rejected(self, api):
        """PRD §3.6: "the logical clock must be at or after the application's
        starts_at and strictly before ends_at..."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        starts = _parse_iso(app["starts_at"])
        set_clock(starts - timedelta(minutes=1))
        resp = api.start_live(app["id"], make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_INVALID_STATE, expected_status=409)


class TestEndLive:
    """PRD §3.6: 'Ending the broadcast transitions operational_status from LIVE
    to COMPLETED...'
    """

    def test_end_live_transitions_to_completed(self, api):
        """PRD §3.6: "Ending the broadcast transitions operational_status from
        LIVE to COMPLETED and requires only that the acting streamer owns the
        application and that the logical clock is at or after the
        application's starts_at."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        app = go_live(streamer, app)
        app = end_live(streamer, app)
        assert app["operational_status"] == "COMPLETED"

    def test_end_live_arms_commission_settlement(self, api):
        """PRD §3.6: "the server initializes a CommissionSettlement for the
        application with status WINDOW_OPEN and return_window_ends_at equal to
        the application's ends_at plus 7 days..."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        app = go_live(streamer, app)
        app = end_live(streamer, app)
        from test_helpers import fetch_settlement
        settlement = fetch_settlement(app["id"])
        assert settlement["status"] == "WINDOW_OPEN"
        # return_window_ends_at = ends_at + 7 days
        ends_at = _parse_iso(app["ends_at"])
        rwe = _parse_iso(settlement["return_window_ends_at"])
        delta = rwe - ends_at
        assert abs(delta - timedelta(days=7)) < timedelta(seconds=2), (
            f"return_window_ends_at = ends_at + 7 days; got delta={delta}"
        )

    def test_end_live_auto_settles_invoice(self, api):
        """PRD §3.6: "The auto-transition from the invoice's DEPOSIT_PAID to
        SETTLED fires the same moment the application's operational_status
        advances to COMPLETED."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        app = go_live(streamer, app)
        app = end_live(streamer, app)
        invoice = fetch_invoice(app["id"])
        assert invoice["status"] == "SETTLED"

    def test_end_live_increments_completed_broadcast_count(self, api):
        """PRD §3.6: "it increments the streamer's completed_broadcast_count by
        1..."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        app = go_live(streamer, app)
        app = end_live(streamer, app)
        from test_helpers import fetch_streamer
        s = fetch_streamer(streamer["id"])
        assert s["completed_broadcast_count"] == streamer["completed_broadcast_count"] + 1


class TestCancelBeforeStart:
    """PRD §3.7: 'A streamer or operations reviewer may cancel a SCHEDULED
    application before it starts, supplying a non-empty reason.'
    """

    def test_cancel_too_late_returns_too_late_to_cancel(self, api):
        """PRD §3.7: "Cancellation requires the logical clock to be strictly
        before the application's starts_at; an attempted cancel at or after
        that instant is rejected with ERR_TOO_LATE_TO_CANCEL (HTTP 409)."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        # Advance clock to exactly starts_at
        set_clock(_parse_iso(app["starts_at"]))
        resp = api.cancel_application(app["id"], cancel_payload("change"), make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_TOO_LATE_TO_CANCEL, expected_status=409)

    def test_cancel_requires_reason(self, api):
        """PRD §3.7: "A missing reason yields ERR_REASON_REQUIRED."""
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        # Empty reason
        resp = api.cancel_application(app["id"], {"reason": ""}, make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_REASON_REQUIRED, expected_status=422)


class TestRefundCalculation:
    """PRD §3.7: 'The refund calculation reads the lead time as the difference
    between the application's starts_at and "now" expressed in seconds and
    divided by 3600.'
    """

    def test_lead_time_72h_full_refund(self, api):
        """# difficulty: boundary_precision_check/refund_lead_time_72h_boundary
        PRD §3.7: "If the lead time is at least 72 hours, the refund equals
        100% of the invoice's deposit_due_cents."
        Also: "When the refund equals the full deposit_due_cents, the invoice
        transitions from DEPOSIT_PAID to REFUNDED_FULL..."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        starts = _parse_iso(app["starts_at"])
        # Set clock exactly 72 hours before starts -> lead_hours == 72
        set_clock(starts - timedelta(hours=72))
        resp = api.cancel_application(app["id"], cancel_payload("change"), make_streamer_headers(streamer["id"]))
        validate_success(resp)
        invoice = fetch_invoice(app["id"])
        assert invoice["refund_cents"] == invoice["deposit_due_cents"]
        assert invoice["status"] == "REFUNDED_FULL"

    def test_lead_time_24h_half_refund(self, api):
        """PRD §3.7: "If the lead time is at least 24 hours but less than 72
        hours, the refund equals one half of deposit_due_cents, rounded
        half-up to integer cents."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        starts = _parse_iso(app["starts_at"])
        set_clock(starts - timedelta(hours=48))
        api.cancel_application(app["id"], cancel_payload("change"), make_streamer_headers(streamer["id"]))
        invoice = fetch_invoice(app["id"])
        # half of deposit_due_cents, round half-up
        from decimal import Decimal, ROUND_HALF_UP
        ddc_original = bundle["invoice"]["deposit_due_cents"]
        expected = int(Decimal(str(ddc_original * 0.5)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        assert invoice["refund_cents"] == expected
        assert invoice["status"] == "REFUNDED_PARTIAL"

    def test_lead_time_under_24h_zero_refund(self, api):
        """PRD §3.7: "If the lead time is less than 24 hours, the refund is 0."""
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        starts = _parse_iso(app["starts_at"])
        set_clock(starts - timedelta(hours=12))
        api.cancel_application(app["id"], cancel_payload("change"), make_streamer_headers(streamer["id"]))
        invoice = fetch_invoice(app["id"])
        assert invoice["refund_cents"] == 0

    def test_cancel_releases_product_associations(self, api):
        """PRD §3.7: "The cancel cascade transitions operational_status from
        SCHEDULED to CANCELLED, runs the refund calculation, applies the
        result to the invoice, and releases every ProductAssociation (each
        becomes RELEASED, with the matching reserved_stock/available_stock
        adjustment on the product)."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        product = bundle["product"]
        starts = _parse_iso(app["starts_at"])
        set_clock(starts - timedelta(hours=80))
        api.cancel_application(app["id"], cancel_payload("change"), make_streamer_headers(streamer["id"]))
        # Check that stock was restored
        from test_helpers.fixtures import get_product
        product_after = get_product(product["id"])
        # association reserved 1 unit by default; available_stock was 100 - 1 = 99
        # After release => 100
        assert product_after["available_stock"] == 100
        assert product_after["reserved_stock"] == 0


class TestForceCancel:
    """PRD §3.7: 'Force-cancellation is the operations-reviewer-only path that
    may terminate a broadcast mid-LIVE.'
    """

    def test_force_cancel_sets_refund_zero(self, api):
        """PRD §3.7: "A force-cancel does not refund the deposit — the
        invoice's refund_cents is set to 0 — and it releases every
        ProductAssociation."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        app = go_live(streamer, app)
        # Force-cancel mid-live
        resp = api.force_cancel_application(app["id"], {"reason": "abuse"}, OPS_HEADERS)
        validate_success(resp)
        invoice = fetch_invoice(app["id"])
        assert invoice["refund_cents"] == 0
        app2 = fetch_application(app["id"])
        assert app2["operational_status"] == "CANCELLED"
