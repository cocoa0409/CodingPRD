"""Session lifecycle — check-in, check-out, abnormal handover, no-show.

PRD §3.6 (Sessions and Usage Logs), §3.5 (final fee calculation).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    advance_clock_to,
    check_in,
    check_out,
    check_out_payload,
    get_equipment,
    get_reservation,
    make_user_headers,
    setup_basic_scenario,
    setup_scenario_with_reservation,
    validate_error,
    validate_success,
)


# ===========================================================================
# Check-in window  (PRD §3.6)
# ===========================================================================
class TestCheckIn:
    """PRD §3.6: 'A User opens a session by checking in on their own
    reservation no earlier than 15 minutes before start_at and strictly
    before end_at. Check-in further requires that the equipment is in
    status AVAILABLE at the moment of the call, and that the bound
    authorization is still APPROVED with expires_at strictly in the
    future — failures yield ERR_INVALID_STATE, ERR_EQUIPMENT_UNAVAILABLE,
    or ERR_AUTHORIZATION_INVALID respectively. A successful check-in
    transitions the reservation from BOOKED to CHECKED_IN and creates a
    UsageLog row whose reservation_id references the reservation and
    whose check_in_at is set to the server clock.'
    """

    def test_check_in_at_start_succeeds(self, api):
        """PRD §3.6: 'A successful check-in transitions the reservation
        from BOOKED to CHECKED_IN and creates a UsageLog row'."""
        s = setup_scenario_with_reservation(
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
        )
        advance_clock_to("2026-05-12T09:00:00.000Z")
        res = api.check_in_reservation(
            s["reservation"]["id"],
            make_user_headers(s["user"]["id"]),
        )
        r = validate_success(res, 200)
        assert r["status"] == "CHECKED_IN"

    def test_check_in_too_early_rejected(self, api):
        """PRD §3.6: 'no earlier than 15 minutes before start_at ...
        failures yield ERR_INVALID_STATE'."""
        s = setup_scenario_with_reservation(
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
        )
        # Clock is at 08:00 (16 minutes-before is 08:45). 08:00 is too
        # early.
        advance_clock_to("2026-05-12T08:00:00.000Z")
        res = api.check_in_reservation(
            s["reservation"]["id"],
            make_user_headers(s["user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_check_in_after_end_rejected(self, api):
        """PRD §3.6: 'strictly before end_at ... failures yield
        ERR_INVALID_STATE'.

        Note: at end_at, the system has already swept the reservation
        to NO_SHOW per PRD §3.6 ('A reservation that is never checked in
        is swept to NO_SHOW when the logical clock advances to or beyond
        end_at'). Either way, check-in must not succeed; the visible
        rejection is ERR_INVALID_STATE because the reservation's state
        is no longer BOOKED."""
        s = setup_scenario_with_reservation(
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
        )
        advance_clock_to("2026-05-12T11:00:00.000Z")
        res = api.check_in_reservation(
            s["reservation"]["id"],
            make_user_headers(s["user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Check-out (PRD §3.6)
# ===========================================================================
class TestCheckOut:
    """PRD §3.6: 'The system sets check_out_at to the server clock,
    computes actual_duration_minutes as the ceiling, in minutes, of
    check_out_at minus check_in_at, computes the final fee per §3.5,
    populates final_fee_cents, final_owner_share_cents, and
    final_platform_fee_cents, and adjusts the lab's
    settlement_balance_cents by the delta between final_owner_share_cents
    and the previously accrued estimated_owner_share_cents (which may be
    positive or negative). The reservation moves to COMPLETED.'
    """

    def test_check_out_transitions_to_completed(self, api):
        """PRD §3.6: 'The reservation moves to COMPLETED'."""
        s = setup_scenario_with_reservation(
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
        )
        advance_clock_to("2026-05-12T09:00:00.000Z")
        r = check_in(reservation=s["reservation"], user=s["user"])
        advance_clock_to("2026-05-12T10:30:00.000Z")
        completed = check_out(reservation=r, user=s["user"])
        assert completed["status"] == "COMPLETED"
        assert completed["final_fee_cents"] >= 0


# ===========================================================================
# Abnormal handover (PRD §3.6)
# ===========================================================================
class TestAbnormalHandover:
    """PRD §3.6: 'When status_handover is ABNORMAL, the system
    additionally spawns a new MaintenanceWindow of kind AD_HOC with
    start_at equal to the server clock and end_at equal to the clock plus
    24 hours ... The window is created in status IN_PROGRESS and the
    equipment is transitioned AVAILABLE → MAINTENANCE.'
    """

    def test_abnormal_checkout_flips_equipment_to_maintenance(self, api):
        """PRD §3.6: 'the equipment is transitioned AVAILABLE →
        MAINTENANCE'."""
        s = setup_scenario_with_reservation(
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
        )
        advance_clock_to("2026-05-12T09:00:00.000Z")
        r = check_in(reservation=s["reservation"], user=s["user"])
        advance_clock_to("2026-05-12T10:30:00.000Z")
        check_out(
            reservation=r, user=s["user"],
            status_handover="ABNORMAL",
            abnormal_event_code="SPILL",
        )
        eq = get_equipment(s["equipment"]["id"])
        assert eq["status"] == "MAINTENANCE"


# ===========================================================================
# No-show (PRD §3.6)
# ===========================================================================
class TestNoShow:
    """PRD §3.6: 'A reservation that is never checked in is swept to
    NO_SHOW when the logical clock advances to or beyond end_at. The
    forfeit is total — estimated_fee_cents is treated as fully charged,
    cancellation_refund_bps remains 0, and the lab's
    settlement_balance_cents retains the previously accrued
    estimated_owner_share_cents.'
    """

    def test_no_show_after_end_at(self, api):
        """PRD §3.6: 'A reservation that is never checked in is swept to
        NO_SHOW when the logical clock advances to or beyond end_at ...
        cancellation_refund_bps remains 0'."""
        s = setup_scenario_with_reservation(
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
        )
        advance_clock_to("2026-05-12T11:00:00.000Z")
        r = get_reservation(s["reservation"]["id"])
        assert r["status"] == "NO_SHOW"
        assert r["cancellation_refund_bps"] == 0
