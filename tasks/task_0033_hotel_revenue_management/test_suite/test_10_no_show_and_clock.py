"""Time-triggered transitions: NO_SHOW, MaintenanceBlock activation /
release, and the logical clock (PRD §3.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    date_plus_days,
    get_clock,
    get_reservation,
    setup_basic_distribution,
    setup_no_show_ready,
    validate_error,
    validate_success,
)


# ===========================================================================
# Logical clock read
# ===========================================================================
class TestLogicalClock:
    def test_get_clock_exposed_to_every_authenticated_role(
        self, api, agent_headers,
    ):
        """PRD §3.7: 'The current logical instant is also readable on
        demand and is exposed to every authenticated role as an object
        containing a single now field.'"""
        # Set a known clock first.
        advance_clock("2031-01-01T12:34:56.000Z")
        res = api.get_clock(agent_headers)
        data = validate_success(res, expected_status=200)
        assert "now" in data

    def test_advance_clock_returns_transitions_triggered(
        self, api, admin_headers,
    ):
        """PRD §3.7: 'A PlatformAdmin may advance that clock by submitting
        a new_now ISO 8601 instant; the response reports the new now and
        the transitions_triggered array.'"""
        res = api.advance_clock("2031-02-01T00:00:00.000Z", admin_headers)
        data = validate_success(res, expected_status=200)
        assert "now" in data
        assert "transitions_triggered" in data
        assert isinstance(data["transitions_triggered"], list)


# ===========================================================================
# NO_SHOW transition
# ===========================================================================
class TestNoShow:
    def test_no_show_triggers_after_check_in_plus_24h(self, api):
        """PRD §3.7: 'a Reservation whose booking_status is CONFIRMED and
        whose assigned_room_id is null transitions automatically to
        NO_SHOW once now() is at or after the reservation's
        check_in_date plus 24 hours.'"""
        ctx = setup_no_show_ready(
            refund_tier_code="MODERATE",
            base_rate_cents=40000,
            check_in_date="2031-03-10",
            check_out_date="2031-03-11",
            initial_clock_iso="2031-03-01T10:00:00.000Z",
        )
        # Advance the clock past 2031-03-11T00:00 (check_in + 24h).
        advance_clock("2031-03-11T01:00:00.000Z")
        res = get_reservation(ctx["reservation"]["id"])
        assert res["booking_status"] == "NO_SHOW"

    def test_moderate_no_show_charge_is_50_percent(self, api):
        """PRD §3.7: 'For MODERATE, the charge is the booked total
        multiplied by 5000, divided by ten thousand, with one half-up
        rounding step (a 50% charge).'"""
        ctx = setup_no_show_ready(
            refund_tier_code="MODERATE",
            base_rate_cents=40000,
            check_in_date="2031-04-10",
            check_out_date="2031-04-11",
            initial_clock_iso="2031-04-01T10:00:00.000Z",
        )
        # booked_total = 40000 (1 night * 40000)
        advance_clock("2031-04-11T01:00:00.000Z")
        res = get_reservation(ctx["reservation"]["id"])
        assert res["booking_status"] == "NO_SHOW"
        # 50% of 40000 = 20000
        assert res["no_show_charge_cents"] == 20000
        # PRD: 'If the resulting no_show_charge_cents is greater than
        # zero, payment_status advances to CAPTURED.'
        assert res["payment_status"] == "CAPTURED"
        # PRD: 'The corresponding refund_amount_cents for a no-show stays
        # at zero — the no-show charge is the financial outcome'.
        assert res["refund_amount_cents"] == 0

    def test_flexible_no_show_charge_is_10_percent(self, api):
        """PRD §3.7: 'For FLEXIBLE, the charge is the booked total
        multiplied by 1000, divided by ten thousand, with one half-up
        rounding step (a 10% charge).'"""
        ctx = setup_no_show_ready(
            refund_tier_code="FLEXIBLE",
            base_rate_cents=40000,
            check_in_date="2031-05-10",
            check_out_date="2031-05-11",
            initial_clock_iso="2031-05-01T10:00:00.000Z",
        )
        advance_clock("2031-05-11T01:00:00.000Z")
        res = get_reservation(ctx["reservation"]["id"])
        assert res["booking_status"] == "NO_SHOW"
        assert res["no_show_charge_cents"] == 4000  # 10% of 40000

    def test_non_refundable_no_show_charge_is_full_total(self, api):
        """PRD §3.7: 'For NON_REFUNDABLE and STRICT tiers, the charge is
        the full booked_total_cents.'"""
        ctx = setup_no_show_ready(
            refund_tier_code="NON_REFUNDABLE",
            base_rate_cents=40000,
            check_in_date="2031-06-10",
            check_out_date="2031-06-11",
            initial_clock_iso="2031-06-01T10:00:00.000Z",
        )
        advance_clock("2031-06-11T01:00:00.000Z")
        res = get_reservation(ctx["reservation"]["id"])
        assert res["booking_status"] == "NO_SHOW"
        assert res["no_show_charge_cents"] == 40000

    def test_strict_no_show_charge_is_full_total(self, api):
        """PRD §3.7: 'For NON_REFUNDABLE and STRICT tiers, the charge is
        the full booked_total_cents.'"""
        ctx = setup_no_show_ready(
            refund_tier_code="STRICT",
            base_rate_cents=40000,
            check_in_date="2031-07-10",
            check_out_date="2031-07-11",
            initial_clock_iso="2031-07-01T10:00:00.000Z",
        )
        advance_clock("2031-07-11T01:00:00.000Z")
        res = get_reservation(ctx["reservation"]["id"])
        assert res["no_show_charge_cents"] == 40000

    def test_dispute_status_initialized_to_none_on_no_show(self, api):
        """PRD §3.7: 'The dispute_status initialises to NONE.'"""
        ctx = setup_no_show_ready(
            refund_tier_code="FLEXIBLE",
            base_rate_cents=40000,
            check_in_date="2031-08-10",
            check_out_date="2031-08-11",
            initial_clock_iso="2031-08-01T10:00:00.000Z",
        )
        advance_clock("2031-08-11T01:00:00.000Z")
        res = get_reservation(ctx["reservation"]["id"])
        assert res["dispute_status"] == "NONE"
