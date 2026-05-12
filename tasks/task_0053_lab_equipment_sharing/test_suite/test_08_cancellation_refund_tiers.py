"""Cancellation refund tiers — 24h / 2h boundary precision.

PRD §3.4 (Cancellation Refund Tiers), §3.3 (cancel preconditions).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    cancel_reservation,
    get_lab,
    get_reservation,
    make_reservation,
    make_user_headers,
    setup_basic_scenario,
    validate_error,
    validate_success,
)


# ===========================================================================
# Refund tier thresholds (PRD §3.4)
# ===========================================================================
class TestRefundTiers:
    """PRD §3.4: 'When that lead is at least 24 hours (the full-refund
    minimum), cancellation_refund_bps is set to 10000 — a complete refund
    of the estimated fee. When the lead is less than 24 hours but at
    least 2 hours (the partial-refund minimum), cancellation_refund_bps
    is set to 5000 — a half refund. When the lead is less than 2 hours,
    cancellation_refund_bps is set to 0 — the reservation still cancels
    but no refund is owed.'
    """

    def test_cancel_exactly_24h_full_refund(self, api):
        """PRD §3.4: 'at least 24 hours (the full-refund minimum),
        cancellation_refund_bps is set to 10000'. The threshold is
        inclusive at exactly 24 hours."""
        s = setup_basic_scenario(initial_clock="2026-05-12T08:00:00.000Z")
        # Reservation starts exactly 24h after current clock.
        r = make_reservation(
            equipment=s["equipment"], user=s["user"],
            authorization=s["authorization"],
            start_at="2026-05-13T08:00:00.000Z",
            end_at="2026-05-13T10:00:00.000Z",
        )
        # No clock advance — cancel now: lead = 1440 minutes exactly.
        cancelled = cancel_reservation(
            reservation=r, user=s["user"],
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_refund_bps"] == 10000

    def test_cancel_23h_partial_refund(self, api):
        """PRD §3.4: 'When the lead is less than 24 hours but at least 2
        hours (the partial-refund minimum), cancellation_refund_bps is
        set to 5000'. Test at 23h lead → 1380 minutes → 5000 bps."""
        s = setup_basic_scenario(initial_clock="2026-05-12T08:00:00.000Z")
        r = make_reservation(
            equipment=s["equipment"], user=s["user"],
            authorization=s["authorization"],
            start_at="2026-05-13T08:00:00.000Z",
            end_at="2026-05-13T10:00:00.000Z",
        )
        # 1 hour later: lead = 23h.
        advance_clock_to("2026-05-12T09:00:00.000Z")
        cancelled = cancel_reservation(
            reservation=r, user=s["user"],
        )
        assert cancelled["cancellation_refund_bps"] == 5000

    def test_cancel_under_2h_no_refund(self, api):
        """PRD §3.4: 'When the lead is less than 2 hours,
        cancellation_refund_bps is set to 0 — the reservation still
        cancels but no refund is owed'."""
        s = setup_basic_scenario(initial_clock="2026-05-12T08:00:00.000Z")
        r = make_reservation(
            equipment=s["equipment"], user=s["user"],
            authorization=s["authorization"],
            start_at="2026-05-12T11:00:00.000Z",
            end_at="2026-05-12T12:00:00.000Z",
        )
        # Advance to 09:30 — 1h30 lead < 2h.
        advance_clock_to("2026-05-12T09:30:00.000Z")
        cancelled = cancel_reservation(
            reservation=r, user=s["user"],
        )
        assert cancelled["cancellation_refund_bps"] == 0
        assert cancelled["status"] == "CANCELLED"

    def test_cancel_at_exactly_2h_partial_refund(self, api):
        """PRD §3.4: 'at least 2 hours (the partial-refund minimum) ...
        is set to 5000' — the threshold is inclusive at 120 minutes."""
        s = setup_basic_scenario(initial_clock="2026-05-12T08:00:00.000Z")
        r = make_reservation(
            equipment=s["equipment"], user=s["user"],
            authorization=s["authorization"],
            start_at="2026-05-12T11:00:00.000Z",
            end_at="2026-05-12T12:00:00.000Z",
        )
        # Lead = exactly 120 minutes.
        advance_clock_to("2026-05-12T09:00:00.000Z")
        cancelled = cancel_reservation(
            reservation=r, user=s["user"],
        )
        assert cancelled["cancellation_refund_bps"] == 5000


# ===========================================================================
# Cancel after start (PRD §3.3)
# ===========================================================================
class TestCancelAfterStart:
    """PRD §3.3: 'A booked reservation can be cancelled by its owning
    User or by a LabOwner of the equipment's lab so long as the server
    clock is strictly before start_at; an attempt after start_at is
    rejected with ERR_INVALID_STATE.'
    """

    def test_cancel_after_start_rejected(self, api):
        """PRD §3.3: 'an attempt after start_at is rejected with
        ERR_INVALID_STATE'."""
        s = setup_basic_scenario(initial_clock="2026-05-12T08:00:00.000Z")
        r = make_reservation(
            equipment=s["equipment"], user=s["user"],
            authorization=s["authorization"],
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T10:00:00.000Z",
        )
        advance_clock_to("2026-05-12T09:00:01.000Z")
        res = api.cancel_reservation(
            r["id"], make_user_headers(s["user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Round-trip lab balance (PRD §3.4, §3.8)
# ===========================================================================
class TestRoundTripBalance:
    """PRD §3.4 + §3.8: 'At reservation create the balance is credited by
    estimated_owner_share_cents ... At a voluntary cancellation it is
    debited by estimated_owner_share_cents multiplied by
    cancellation_refund_bps divided by 10000, rounded half-up.'

    With a full-refund cancellation the credit and debit cancel exactly.
    """

    def test_full_refund_cancel_restores_balance(self, api):
        """PRD §3.4: 'a complete refund of the estimated fee' implies the
        lab's balance is unchanged after a 100% refund cycle."""
        s = setup_basic_scenario(initial_clock="2026-05-12T08:00:00.000Z")
        before = get_lab(s["lab"]["id"])["settlement_balance_cents"]
        r = make_reservation(
            equipment=s["equipment"], user=s["user"],
            authorization=s["authorization"],
            start_at="2026-05-13T09:00:00.000Z",
            end_at="2026-05-13T10:00:00.000Z",
        )
        # 25h advance still leaves us >24h before start_at.
        cancel_reservation(reservation=r, user=s["user"])
        after = get_lab(s["lab"]["id"])["settlement_balance_cents"]
        assert after == before
