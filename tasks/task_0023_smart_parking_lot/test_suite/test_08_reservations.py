"""Reservations: hold, match, expire, cancel (PRD §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    advance_clock,
    api_client,
    bind_vehicle_to_card,
    create_card,
    create_lot,
    create_reservation_payload,
    create_session_payload,
    create_space,
    create_vehicle,
    create_zone,
    get_reservation,
    get_session,
    get_space,
    make_driver_headers,
    open_session,
    recharge_card,
    run_sweep,
    setup_held_reservation,
    setup_lot_zone_spaces,
    TEST_USERS,
    unique_external_ref,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.4 — Window validation
# ===========================================================================
class TestReservationWindowValidation:
    def test_end_at_or_before_start_rejected(self, api):
        """PRD §3.4: 'The reservation window must satisfy scheduled_end_at
        strictly greater than scheduled_start_at ... a violation yields
        ERR_INVALID_RESERVATION_WINDOW.'"""
        advance_clock("2026-04-01T12:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
        vehicle = create_vehicle()
        card = create_card(card_type="STORED_VALUE")
        bind_vehicle_to_card(card["id"], vehicle["id"])
        recharge_card(card["id"], amount_cents=10_000,
                      external_ref=unique_external_ref())
        payload = create_reservation_payload(
            zone_id=zone["id"],
            vehicle_id=vehicle["id"],
            scheduled_start_at="2026-04-01T14:00:00.000Z",
            scheduled_end_at="2026-04-01T13:00:00.000Z",  # end < start
            card_id=card["id"],
        )
        res = api.create_reservation(
            lot["id"], payload, make_driver_headers(vehicle["id"])
        )
        validate_error(res, "ERR_INVALID_RESERVATION_WINDOW")

    def test_start_too_far_in_past_rejected(self, api):
        """PRD §3.4: 'scheduled_start_at must be at least five minutes
        earlier than the current instant (i.e. scheduled_start_at must be
        at or after the current instant minus five minutes); a violation
        yields ERR_INVALID_RESERVATION_WINDOW.'"""
        advance_clock("2026-04-01T14:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
        vehicle = create_vehicle()
        card = create_card(card_type="STORED_VALUE")
        bind_vehicle_to_card(card["id"], vehicle["id"])
        recharge_card(card["id"], amount_cents=10_000,
                      external_ref=unique_external_ref())
        # 10 minutes in the past — definitely > 5min before now
        payload = create_reservation_payload(
            zone_id=zone["id"],
            vehicle_id=vehicle["id"],
            scheduled_start_at="2026-04-01T13:50:00.000Z",
            scheduled_end_at="2026-04-01T15:00:00.000Z",
            card_id=card["id"],
        )
        res = api.create_reservation(
            lot["id"], payload, make_driver_headers(vehicle["id"])
        )
        validate_error(res, "ERR_INVALID_RESERVATION_WINDOW")


# ===========================================================================
# §3.4 — Selector / space allocation
# ===========================================================================
class TestSelector:
    def test_selector_picks_lex_smallest_label(self, api):
        """PRD §3.4: 'Among candidates, the selector picks the space with
        the lexicographically smallest label.'"""
        advance_clock("2026-04-02T13:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(
            space_count=3, space_labels=["B-1", "A-1", "C-1"]
        )
        vehicle = create_vehicle()
        card = create_card(card_type="STORED_VALUE")
        bind_vehicle_to_card(card["id"], vehicle["id"])
        recharge_card(card["id"], amount_cents=10_000,
                      external_ref=unique_external_ref())
        payload = create_reservation_payload(
            zone_id=zone["id"],
            vehicle_id=vehicle["id"],
            scheduled_start_at="2026-04-02T14:00:00.000Z",
            scheduled_end_at="2026-04-02T16:00:00.000Z",
            card_id=card["id"],
        )
        res = api.create_reservation(
            lot["id"], payload, make_driver_headers(vehicle["id"])
        )
        data = validate_success(res, expected_status=201)
        # The "A-1" space is lex-smallest.
        a1 = next(s for s in spaces if s["label"] == "A-1")
        assert data["space_id"] == a1["id"]


# ===========================================================================
# §3.4 — Cancel terminal branch
# ===========================================================================
class TestCancelReservation:
    def test_cancel_outside_no_cancel_window_zero_penalty(self, api):
        """PRD §3.4: 'If the cancellation arrives earlier than that,
        penalty_charged_cents stays zero and no penalty payment is created.'"""
        # cancel arrives 60 min before scheduled_start_at — outside 30-min window
        scen = setup_held_reservation(
            base_iso="2026-04-03T13:00:00.000Z",
            scheduled_start_at="2026-04-03T14:00:00.000Z",
            scheduled_end_at="2026-04-03T15:00:00.000Z",
            no_show_penalty_cents=500,
        )
        # Now still 13:00 → start at 14:00 → 60 min before
        res = api.cancel_reservation(
            scen["reservation"]["id"],
            make_driver_headers(scen["vehicle"]["id"]),
        )
        validate_success(res, expected_status=200)
        r = get_reservation(scen["reservation"]["id"])
        assert r["status"] == "CANCELLED"
        assert r["penalty_charged_cents"] == 0

    def test_cancel_inside_no_cancel_window_half_penalty(self, api):
        """PRD §3.4: 'If the cancellation arrives at or after
        scheduled_start_at minus thirty minutes — the no-cancel window —
        penalty_charged_cents is set to half of the lot's
        no_show_penalty_cents, divided in integer cents and rounded
        half-up to the nearest cent.'"""
        scen = setup_held_reservation(
            base_iso="2026-04-04T13:00:00.000Z",
            scheduled_start_at="2026-04-04T14:00:00.000Z",
            scheduled_end_at="2026-04-04T15:00:00.000Z",
            no_show_penalty_cents=500,
        )
        # advance to 13:35 — 25 min before start, inside no-cancel window
        advance_clock("2026-04-04T13:35:00.000Z")
        res = api.cancel_reservation(
            scen["reservation"]["id"],
            make_driver_headers(scen["vehicle"]["id"]),
        )
        validate_success(res, expected_status=200)
        r = get_reservation(scen["reservation"]["id"])
        assert r["status"] == "CANCELLED"
        # half of 500 = 250
        assert r["penalty_charged_cents"] == 250

    def test_cancel_clears_space_reservation_lock(self, api):
        """PRD §3.4: 'Reservation.status moves from HELD to CANCELLED, the
        holding Space.reservation_lock is cleared to UNRESERVED.'"""
        scen = setup_held_reservation(
            base_iso="2026-04-05T13:00:00.000Z",
            scheduled_start_at="2026-04-05T14:00:00.000Z",
            scheduled_end_at="2026-04-05T15:00:00.000Z",
        )
        api.cancel_reservation(
            scen["reservation"]["id"],
            make_driver_headers(scen["vehicle"]["id"]),
        )
        sp = get_space(
            scen["lot"]["id"], scen["zone"]["id"], scen["space"]["id"]
        )
        assert sp["reservation_lock"] == "UNRESERVED"


# ===========================================================================
# §3.4 — Expire NO_SHOW
# ===========================================================================
class TestReservationExpire:
    def test_clock_advance_past_hold_expires_to_no_show(self, api):
        """PRD §3.4: 'A clock advance that crosses scheduled_start_at plus
        the lot's reservation_hold_minutes while matched_session_id is
        still null transitions the reservation from HELD to
        EXPIRED_NO_SHOW.'"""
        scen = setup_held_reservation(
            base_iso="2026-04-06T13:50:00.000Z",
            scheduled_start_at="2026-04-06T14:00:00.000Z",
            scheduled_end_at="2026-04-06T16:00:00.000Z",
            reservation_hold_minutes=15,
            no_show_penalty_cents=500,
        )
        # Advance to 14:16 — past the 15-min hold window from 14:00
        advance_clock("2026-04-06T14:16:00.000Z")
        run_sweep()
        r = get_reservation(scen["reservation"]["id"])
        assert r["status"] == "EXPIRED_NO_SHOW"
        assert r["penalty_charged_cents"] == 500


# ===========================================================================
# §3.4 — Match a HELD reservation via gate-in
# ===========================================================================
class TestMatchReservation:
    def test_gate_in_within_window_matches_reservation(self, api):
        """PRD §3.4: 'A gate-in by the reservation's vehicle whose entry
        instant lies within the matching window — at or after
        scheduled_start_at minus five minutes and at or before
        scheduled_start_at plus the lot's reservation_hold_minutes — and
        whose space matches the reservation's space_id ... transitions the
        reservation from HELD to MATCHED.'"""
        scen = setup_held_reservation(
            base_iso="2026-04-07T13:50:00.000Z",
            scheduled_start_at="2026-04-07T14:00:00.000Z",
            scheduled_end_at="2026-04-07T16:00:00.000Z",
            hourly_rate_cents=300,
            reservation_hold_minutes=15,
        )
        advance_clock("2026-04-07T14:00:00.000Z")
        # Gate-in via GateSystem on the reserved space
        session = open_session(
            scen["lot"]["id"],
            vehicle_id=scen["vehicle"]["id"],
            space_id=scen["space"]["id"],
        )
        r = get_reservation(scen["reservation"]["id"])
        assert r["status"] == "MATCHED"
        assert r["matched_session_id"] == session["id"]
