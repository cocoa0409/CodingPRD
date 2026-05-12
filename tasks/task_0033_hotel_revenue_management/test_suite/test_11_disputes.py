"""Disputes (PRD §3.8)."""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    cancel_reservation,
    get_reservation,
    resolve_dispute_payload,
    setup_basic_distribution,
    setup_no_show_ready,
    validate_error,
    validate_success,
)


# ===========================================================================
# Open dispute on a NO_SHOW
# ===========================================================================
class TestOpenDispute:
    def test_open_dispute_on_no_show_advances_to_open(self, api, guest_headers):
        """PRD §3.8: 'A Guest or ReservationsAgent may open a dispute
        against a reservation that has gone to NO_SHOW or CANCELLED with
        a residual penalty. Opening a dispute moves dispute_status from
        NONE to OPEN.'"""
        ctx = setup_no_show_ready(
            refund_tier_code="MODERATE",
            base_rate_cents=40000,
            check_in_date="2032-01-10",
            check_out_date="2032-01-11",
            initial_clock_iso="2032-01-01T10:00:00.000Z",
        )
        advance_clock("2032-01-11T01:00:00.000Z")
        res = get_reservation(ctx["reservation"]["id"])
        assert res["booking_status"] == "NO_SHOW"
        # Open dispute
        resp = api.open_dispute(ctx["reservation"]["id"], guest_headers)
        opened = validate_success(resp, expected_status=200)
        assert opened["dispute_status"] == "OPEN"
        # PRD §3.5: parallel state — booking_status remains NO_SHOW.
        assert opened["booking_status"] == "NO_SHOW"


# ===========================================================================
# Resolve dispute
# ===========================================================================
class TestResolveDispute:
    def test_resolve_in_favor_of_guest_refunds_and_advances_state(
        self, api, guest_headers, admin_headers,
    ):
        """PRD §3.8: 'When resolution is GUEST, the system reverses the
        financial outcome — the refund_amount_cents is set to whichever
        penalty applied (the no_show_charge_cents if the reservation
        reached NO_SHOW ...) — payment_status is moved to REFUNDED_FULL,
        and dispute_status advances to RESOLVED_GUEST.'"""
        ctx = setup_no_show_ready(
            refund_tier_code="MODERATE",
            base_rate_cents=40000,
            check_in_date="2032-02-10",
            check_out_date="2032-02-11",
            initial_clock_iso="2032-02-01T10:00:00.000Z",
        )
        advance_clock("2032-02-11T01:00:00.000Z")
        res = get_reservation(ctx["reservation"]["id"])
        assert res["no_show_charge_cents"] == 20000
        api.open_dispute(ctx["reservation"]["id"], guest_headers)
        resp = api.resolve_dispute(
            ctx["reservation"]["id"],
            resolve_dispute_payload(resolution="GUEST"),
            admin_headers,
        )
        resolved = validate_success(resp, expected_status=200)
        assert resolved["dispute_status"] == "RESOLVED_GUEST"
        assert resolved["payment_status"] == "REFUNDED_FULL"
        assert resolved["refund_amount_cents"] == 20000

    def test_resolve_in_favor_of_hotel_no_money_change(
        self, api, guest_headers, admin_headers,
    ):
        """PRD §3.8: 'When resolution is HOTEL, no monetary change occurs
        and dispute_status advances to RESOLVED_HOTEL.'"""
        ctx = setup_no_show_ready(
            refund_tier_code="MODERATE",
            base_rate_cents=40000,
            check_in_date="2032-03-10",
            check_out_date="2032-03-11",
            initial_clock_iso="2032-03-01T10:00:00.000Z",
        )
        advance_clock("2032-03-11T01:00:00.000Z")
        res_before = get_reservation(ctx["reservation"]["id"])
        api.open_dispute(ctx["reservation"]["id"], guest_headers)
        resp = api.resolve_dispute(
            ctx["reservation"]["id"],
            resolve_dispute_payload(resolution="HOTEL"),
            admin_headers,
        )
        resolved = validate_success(resp, expected_status=200)
        assert resolved["dispute_status"] == "RESOLVED_HOTEL"
        # PRD §3.8: 'no monetary change occurs'
        assert resolved["refund_amount_cents"] == res_before["refund_amount_cents"]
        assert resolved["payment_status"] == res_before["payment_status"]
        assert resolved["no_show_charge_cents"] == res_before["no_show_charge_cents"]
