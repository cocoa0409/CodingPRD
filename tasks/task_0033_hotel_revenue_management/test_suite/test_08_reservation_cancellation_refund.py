"""Reservation cancellation and refund (PRD §3.5).

Covers the four refund tiers and the lead-time bucket lookup. Single
half-up rounding step at the end (per-night refund rounding is
explicitly forbidden by PRD §2.8 / §3.5).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    cancel_reservation,
    create_confirmed_reservation,
    create_pending_reservation,
    setup_basic_distribution,
    validate_error,
    validate_success,
)


# ===========================================================================
# Cancel from PENDING — zero money movement invariant
# ===========================================================================
class TestCancelFromPending:
    def test_cancel_pending_zero_refund(self, api):
        """PRD §3.5: 'From PENDING, the reservation has never been
        charged: refund_amount_cents is set to zero, and if
        payment_status was AUTHORIZED it is moved to REFUNDED_FULL
        (otherwise unchanged).'"""
        scaffold = setup_basic_distribution(n_rooms=1)
        res = create_pending_reservation(
            scaffold,
            check_in_date="2029-03-01", check_out_date="2029-03-02",
        )
        cancelled = cancel_reservation(res["id"])
        assert cancelled["booking_status"] == "CANCELLED"
        assert cancelled["refund_amount_cents"] == 0
        # PRD: payment_status was UNPAID and stays UNPAID.
        assert cancelled["payment_status"] == "UNPAID"
        assert cancelled["no_show_charge_cents"] == 0
        assert cancelled["walkout_compensation_cents"] == 0


# ===========================================================================
# Cancel from CONFIRMED — refund tier formula
# ===========================================================================
class TestCancelRefundTiers:
    def test_flexible_full_refund_at_or_above_24h(self, api):
        """PRD §3.5: 'For FLEXIBLE, the refund ratio is 10000 bp (a full
        refund) when lead_time_hours is at least 24, and 5000 bp (a half
        refund) otherwise.'

        Set clock to 2029-04-05 09:00; booking check_in 2029-04-10
        midnight (lead = 5 days = 120h ≥ 24).  Full refund expected.
        """
        advance_clock("2029-04-05T09:00:00.000Z")
        scaffold = setup_basic_distribution(
            base_rate_cents=20000, n_rooms=2,
            channel_type="DIRECT",
            refund_tier_code="FLEXIBLE",
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2029-04-10", check_out_date="2029-04-12",
        )
        # 2 nights * 20000 = 40000 booked_total
        assert res["booked_total_cents"] == 40000
        cancelled = cancel_reservation(res["id"])
        assert cancelled["refund_amount_cents"] == 40000
        assert cancelled["payment_status"] == "REFUNDED_FULL"

    def test_flexible_half_refund_inside_24h(self, api):
        """PRD §3.5: 'For FLEXIBLE, the refund ratio is ... 5000 bp
        (a half refund) otherwise.' (i.e., lead_time_hours < 24)"""
        advance_clock("2029-04-09T13:00:00.000Z")  # ~11h lead
        scaffold = setup_basic_distribution(
            base_rate_cents=20000, n_rooms=2,
            channel_type="DIRECT",
            refund_tier_code="FLEXIBLE",
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2029-04-10", check_out_date="2029-04-12",
        )
        cancelled = cancel_reservation(res["id"])
        # 50% of 40000 = 20000
        assert cancelled["refund_amount_cents"] == 20000
        assert cancelled["payment_status"] == "REFUNDED_PARTIAL"

    def test_moderate_full_refund_at_or_above_168h(self, api):
        """PRD §3.5: 'For MODERATE, the refund ratio is 10000 bp when
        lead_time_hours is at least 168 (one week)'."""
        advance_clock("2029-05-01T10:00:00.000Z")
        scaffold = setup_basic_distribution(
            base_rate_cents=20000, n_rooms=2,
            channel_type="DIRECT",
            refund_tier_code="MODERATE",
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2029-05-15", check_out_date="2029-05-17",
        )
        cancelled = cancel_reservation(res["id"])
        assert cancelled["refund_amount_cents"] == 40000
        assert cancelled["payment_status"] == "REFUNDED_FULL"

    def test_moderate_half_refund_in_72_to_168_window(self, api):
        """PRD §3.5: 'For MODERATE, the refund ratio is ... 5000 bp when
        lead_time_hours is at least 72 but less than 168'."""
        # check_in 2029-05-15 → midnight; clock 2029-05-09T10:00 →
        # lead = 134h (between 72 and 168).
        advance_clock("2029-05-09T10:00:00.000Z")
        scaffold = setup_basic_distribution(
            base_rate_cents=20000, n_rooms=2,
            channel_type="DIRECT",
            refund_tier_code="MODERATE",
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2029-05-15", check_out_date="2029-05-17",
        )
        cancelled = cancel_reservation(res["id"])
        assert cancelled["refund_amount_cents"] == 20000
        assert cancelled["payment_status"] == "REFUNDED_PARTIAL"

    def test_moderate_no_refund_inside_72h(self, api):
        """PRD §3.5: 'For MODERATE, the refund ratio is ... 0 bp (no
        refund) when lead_time_hours is less than 72.'"""
        advance_clock("2029-05-13T20:00:00.000Z")  # ~28h lead
        scaffold = setup_basic_distribution(
            base_rate_cents=20000, n_rooms=2,
            channel_type="DIRECT",
            refund_tier_code="MODERATE",
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2029-05-15", check_out_date="2029-05-17",
        )
        cancelled = cancel_reservation(res["id"])
        assert cancelled["refund_amount_cents"] == 0
        # PRD §3.5: 'If the refund is zero, the payment_status becomes
        # CAPTURED — the property has retained the full booking value as
        # a cancellation penalty.'
        assert cancelled["payment_status"] == "CAPTURED"

    def test_strict_half_refund_at_or_above_336h(self, api):
        """PRD §3.5: 'For STRICT, the refund ratio is 5000 bp when
        lead_time_hours is at least 336 (two weeks), and 0 bp otherwise.'

        check_in is 2029-06-15 (local midnight); the cancellation must
        occur at or before 2029-06-01T00:00:00Z so lead_time_hours is
        exactly 336 (the >= boundary). The previous clock value of
        2029-06-01T10:00:00Z gave 326 h — under the threshold — and
        produced refund 0, contradicting the test's intent.
        """
        advance_clock("2029-06-01T00:00:00.000Z")  # exactly 336h lead
        scaffold = setup_basic_distribution(
            base_rate_cents=20000, n_rooms=2,
            channel_type="DIRECT",
            refund_tier_code="STRICT",
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2029-06-15", check_out_date="2029-06-17",
        )
        cancelled = cancel_reservation(res["id"])
        assert cancelled["refund_amount_cents"] == 20000
        assert cancelled["payment_status"] == "REFUNDED_PARTIAL"

    def test_strict_no_refund_inside_336h(self, api):
        """PRD §3.5: 'For STRICT, the refund ratio is ... 0 bp
        otherwise.' (i.e., lead_time_hours < 336)"""
        advance_clock("2029-06-10T10:00:00.000Z")  # ~5 days lead
        scaffold = setup_basic_distribution(
            base_rate_cents=20000, n_rooms=2,
            channel_type="DIRECT",
            refund_tier_code="STRICT",
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2029-06-15", check_out_date="2029-06-17",
        )
        cancelled = cancel_reservation(res["id"])
        assert cancelled["refund_amount_cents"] == 0
        assert cancelled["payment_status"] == "CAPTURED"

    def test_non_refundable_zero_at_any_lead(self, api):
        """PRD §3.5: 'For NON_REFUNDABLE, the refund ratio is 0 bp at any
        lead time.'"""
        advance_clock("2029-07-01T10:00:00.000Z")  # ~14 days lead
        scaffold = setup_basic_distribution(
            base_rate_cents=20000, n_rooms=2,
            channel_type="DIRECT",
            refund_tier_code="NON_REFUNDABLE",
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2029-07-15", check_out_date="2029-07-17",
        )
        cancelled = cancel_reservation(res["id"])
        assert cancelled["refund_amount_cents"] == 0
        assert cancelled["payment_status"] == "CAPTURED"


# ===========================================================================
# Single rounding step on refund (PRD §2.8, §3.5)
# ===========================================================================
class TestRefundSingleRounding:
    def test_refund_uses_single_rounding_not_per_night(self, api):
        """PRD §3.5: 'with a single half-up rounding applied to the
        final result — never a per-night refund and never an
        intermediate rounding.'

        Setup: base_rate = 12001 cents/night, 2 nights → booked_total
        24002 cents. FLEXIBLE @ <24h lead → 5000 bp = 50%.

        Single-rounding result: round_half_up(24002 * 5000 / 10000)
        = round_half_up(12001.0) = 12001.
        Per-night-rounded result (forbidden) would be
        round(12001*0.5)+round(12001*0.5) = 6001+6001 = 12002.
        """
        advance_clock("2029-08-09T13:00:00.000Z")  # ~21h lead
        scaffold = setup_basic_distribution(
            base_rate_cents=12001, n_rooms=2,
            channel_type="DIRECT",
            refund_tier_code="FLEXIBLE",
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2029-08-10", check_out_date="2029-08-12",
        )
        assert res["booked_total_cents"] == 24002
        cancelled = cancel_reservation(res["id"])
        assert cancelled["refund_amount_cents"] == 12001, (
            "single-rounding must yield 12001; per-night rounding "
            "(forbidden) would yield 12002"
        )
