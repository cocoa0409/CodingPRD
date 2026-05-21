"""Tap-out and incomplete-trip sweep — PRD §3.6.

Covers the TAPPED_IN → COMPLETED transition, the strictly-after
constraint, and the system-initiated INCOMPLETE_FORCED close at the
180-minute boundary.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    INCOMPLETE_FORCED_MINUTES,
    advance_clock_to_iso,
    add_minutes,
    make_rider_headers,
    run_sweep_incomplete_trips,
    setup_rider_with_funded_card,
    tap_in,
    tap_out_payload,
    validate_error,
    validate_success,
)


class TestTapOut:

    def test_tap_out_transitions_to_completed(self, api):
        """PRD §3.6: "When the rider taps out ... Success writes
        `tap_out_at`, transitions `travel_status` from `TAPPED_IN` to
        `COMPLETED`, and refreshes `updated_at`."

        Claim: tap-out moves travel_status to COMPLETED and sets
        tap_out_at."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        trip = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        rh = make_rider_headers(rider["id"])
        resp = api.tap_out(
            trip["id"],
            tap_out_payload(tap_out_at="2026-05-20T10:20:00.000Z"),
            rh,
        )
        completed = validate_success(resp, expected_status=200)
        assert completed["travel_status"] == "COMPLETED"
        assert completed.get("tap_out_at"), (
            "tap_out_at must be set on COMPLETED"
        )

    def test_tap_out_equal_to_tap_in_rejected(self, api):
        """PRD §3.6: "`tap_out_at` is strictly greater than `tap_in_at`
        (otherwise `ERR_TAP_OUT_NOT_AFTER_TAP_IN`)".

        Claim: tap_out_at == tap_in_at is rejected with
        ERR_TAP_OUT_NOT_AFTER_TAP_IN."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        trip = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        rh = make_rider_headers(rider["id"])
        resp = api.tap_out(
            trip["id"],
            tap_out_payload(tap_out_at="2026-05-20T10:00:00.000Z"),
            rh,
        )
        validate_error(
            resp, ApiErrorId.ERR_TAP_OUT_NOT_AFTER_TAP_IN.value,
        )

    def test_tap_out_before_tap_in_rejected(self, api):
        """PRD §3.6: "`tap_out_at` is strictly greater than
        `tap_in_at`".

        Claim: tap_out_at < tap_in_at is rejected with
        ERR_TAP_OUT_NOT_AFTER_TAP_IN."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        trip = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        rh = make_rider_headers(rider["id"])
        resp = api.tap_out(
            trip["id"],
            tap_out_payload(tap_out_at="2026-05-20T09:59:00.000Z"),
            rh,
        )
        validate_error(
            resp, ApiErrorId.ERR_TAP_OUT_NOT_AFTER_TAP_IN.value,
        )


class TestIncompleteSweep:

    def test_sweep_force_closes_after_180_minutes(self, api):
        """PRD §3.6: "When a rider taps in but never taps out, the
        incomplete-trip sweep closes the trip on the rider's behalf.
        The sweep walks every trip whose `travel_status` is
        `TAPPED_IN` and whose `tap_in_at` plus one hundred eighty
        minutes is at or before the current server clock and
        force-closes each one: `tap_out_at` is written to `tap_in_at`
        plus one hundred eighty minutes, and `travel_status`
        transitions to terminal `INCOMPLETE_FORCED`."

        Claim: an open tap-in at T, with clock at T+180min, is closed
        by the sweep with travel_status=INCOMPLETE_FORCED and
        tap_out_at = T + 180 min."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        trip = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        # Advance to tap_in + 180 minutes exactly.
        advance_clock_to_iso("2026-05-20T13:00:00.000Z")
        run_sweep_incomplete_trips()
        # Read the trip back.
        from test_helpers import get_trip
        closed = get_trip(trip["id"])
        assert closed["travel_status"] == "INCOMPLETE_FORCED", (
            "Trip must move to INCOMPLETE_FORCED after sweep at "
            f"180 min; got travel_status={closed['travel_status']}"
        )
        assert closed.get("tap_out_at") == "2026-05-20T13:00:00.000Z", (
            "tap_out_at must equal tap_in_at + 180 minutes; got "
            f"{closed.get('tap_out_at')!r}"
        )

    def test_sweep_does_not_close_before_180_minutes(self, api):
        """PRD §3.6: "whose `tap_in_at` plus one hundred eighty minutes
        is at or before the current server clock".

        Claim: at 179 minutes after tap-in, the sweep leaves the trip
        in TAPPED_IN (the boundary is at-or-after, so before it the
        sweep is a no-op for this trip)."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        trip = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        # Advance to tap_in + 179 minutes (< 180).
        advance_clock_to_iso("2026-05-20T12:59:00.000Z")
        run_sweep_incomplete_trips()
        from test_helpers import get_trip
        still_open = get_trip(trip["id"])
        assert still_open["travel_status"] == "TAPPED_IN", (
            "Trip must remain TAPPED_IN below the 180-min threshold; "
            f"got travel_status={still_open['travel_status']}"
        )
