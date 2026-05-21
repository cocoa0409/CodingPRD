"""SlipTransferRequest lifecycle — PRD §3.7.

REQUESTED → OFFERED → ACCEPTED (or → DECLINED → REQUESTED via /requeue,
or OFFERED → EXPIRED via ops/run past offer_expires_at).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    accept_slip_transfer,
    advance_clock_to_iso,
    decline_slip_transfer,
    get_reservation,
    offer_slip_transfer,
    request_slip_transfer,
    requeue_slip_transfer,
    setup_two_slip_marina_with_active_reservation,
    validate_error,
)


# ===========================================================================
# Transfer request happy path — PRD §3.7
# ===========================================================================
class TestTransferLifecycle:

    def test_requested_then_offered(self, api, dock_master_headers):
        """PRD §3.7: "A `DockMaster` reviews it and, if the move is
        acceptable, transitions it to `OFFERED`..."

        Claim: REQUESTED → OFFERED succeeds when the desired slip
        size-matches and is AVAILABLE."""
        scenario = setup_two_slip_marina_with_active_reservation()
        tr = request_slip_transfer(
            scenario["marina"]["id"], scenario["boater"],
            scenario["reservation"]["id"], scenario["s2"]["id"],
        )
        assert tr["status"] == "REQUESTED"
        offered = offer_slip_transfer(
            scenario["marina"]["id"], tr["id"],
        )
        assert offered["status"] == "OFFERED"

    def test_offer_sets_expires_at_24h_after_clock(
        self, api, dock_master_headers,
    ):
        """PRD §3.7: "on success the system sets `offer_expires_at` to
        the marina's `current_date` plus twenty-four hours."

        Claim: offer_expires_at is exactly 24 hours past
        marina.current_date at the moment of offer.

        We pin the marina clock to a known instant first."""
        scenario = setup_two_slip_marina_with_active_reservation()
        # Anchor the marina clock.
        advance_clock_to_iso(
            scenario["marina"]["id"], "2024-04-15T10:00:00.000Z",
        )
        tr = request_slip_transfer(
            scenario["marina"]["id"], scenario["boater"],
            scenario["reservation"]["id"], scenario["s2"]["id"],
        )
        offered = offer_slip_transfer(
            scenario["marina"]["id"], tr["id"],
        )
        assert offered["offer_expires_at"] == "2024-04-16T10:00:00.000Z", (
            f"Expected offer_expires_at = clock + 24h = "
            f"2024-04-16T10:00:00.000Z, got "
            f"{offered['offer_expires_at']!r}"
        )

    def test_accept_updates_reservation_slip_and_recomputes_estimate(
        self, api, dock_master_headers,
    ):
        """PRD §3.7: "on success the source reservation's `slip_id` is
        updated to `desired_slip_id` and its `estimated_total_cents` is
        recomputed using the new slip's `flat_daily_charge_cents`..."

        Claim: after ACCEPT, source reservation now has slip_id ==
        desired_slip and the estimated_total_cents reflects the new
        slip's flat_daily_charge_cents."""
        scenario = setup_two_slip_marina_with_active_reservation(
            base_daily_rate_cents=500,
            check_in_date="2024-04-01T00:00:00.000Z",
            check_out_date="2024-04-03T00:00:00.000Z",
        )
        tr = request_slip_transfer(
            scenario["marina"]["id"], scenario["boater"],
            scenario["reservation"]["id"], scenario["s2"]["id"],
        )
        offer_slip_transfer(scenario["marina"]["id"], tr["id"])
        # Clock under offer_expires_at — we have not advanced clock so
        # marina clock is still at epoch (1970), which IS strictly less
        # than offer_expires_at (epoch + 24h).
        accepted = accept_slip_transfer(
            scenario["marina"]["id"], scenario["boater"], tr["id"],
        )
        assert accepted["status"] == "ACCEPTED"
        # Source reservation now references the new slip.
        reservation_now = get_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
        )
        assert reservation_now["slip_id"] == scenario["s2"]["id"], (
            f"After accept, reservation.slip_id must be the new slip "
            f"id, got {reservation_now['slip_id']!r}"
        )
        # estimated_total_cents reflects the new slip's
        # flat_daily_charge_cents (2500 vs s1's 2000) — 2 nights
        # SHOULDER in April: per_night_raw = 500*30*1.20 + 2500 = 20500.
        # Old s1 number was per_night_raw = 500*30*1.20 + 2000 = 20000.
        assert reservation_now["estimated_total_cents"] == 20500 * 2, (
            f"After transfer to s2 (flat=2500), estimated_total_cents "
            f"must be 41000 = 20500*2 nights at SHOULDER, got "
            f"{reservation_now['estimated_total_cents']!r}"
        )

    def test_decline_then_requeue_then_offer_again(
        self, api, dock_master_headers,
    ):
        """PRD §3.7: "A boater can re-queue a declined request,
        transitioning `DECLINED` back to `REQUESTED`, provided the
        source reservation is still in `APPROVED` or `CHECKED_IN`."

        Claim: REQUESTED → OFFERED → DECLINED → REQUESTED → OFFERED is
        achievable on the same SlipTransferRequest id (cyclic)."""
        scenario = setup_two_slip_marina_with_active_reservation()
        tr = request_slip_transfer(
            scenario["marina"]["id"], scenario["boater"],
            scenario["reservation"]["id"], scenario["s2"]["id"],
        )
        original_id = tr["id"]
        # REQUESTED → OFFERED
        offered = offer_slip_transfer(scenario["marina"]["id"], tr["id"])
        assert offered["status"] == "OFFERED"
        # OFFERED → DECLINED
        declined = decline_slip_transfer(
            scenario["marina"]["id"], scenario["boater"], tr["id"],
        )
        assert declined["status"] == "DECLINED"
        # DECLINED → REQUESTED
        requeued = requeue_slip_transfer(
            scenario["marina"]["id"], scenario["boater"], tr["id"],
        )
        assert requeued["status"] == "REQUESTED"
        assert requeued["id"] == original_id, (
            "Cyclic re-queue must not change the SlipTransferRequest id"
        )
        # REQUESTED → OFFERED again
        offered_again = offer_slip_transfer(
            scenario["marina"]["id"], tr["id"],
        )
        assert offered_again["status"] == "OFFERED"
        assert offered_again["id"] == original_id


# ===========================================================================
# Offer expiry via ops/run — PRD §3.7
# ===========================================================================
class TestOfferExpiry:

    def test_offer_expires_after_clock_past_offer_expires_at(
        self, api, dock_master_headers,
    ):
        """PRD §3.7: "If the offer expires unaccepted — the marina
        clock has reached or passed `offer_expires_at` — the next ops
        sweep transitions it to `EXPIRED`."

        Claim: after clock past offer_expires_at and an ops/run, the
        request is EXPIRED."""
        scenario = setup_two_slip_marina_with_active_reservation()
        # Anchor clock.
        advance_clock_to_iso(
            scenario["marina"]["id"], "2024-04-15T10:00:00.000Z",
        )
        tr = request_slip_transfer(
            scenario["marina"]["id"], scenario["boater"],
            scenario["reservation"]["id"], scenario["s2"]["id"],
        )
        offered = offer_slip_transfer(
            scenario["marina"]["id"], tr["id"],
        )
        assert offered["offer_expires_at"] == "2024-04-16T10:00:00.000Z"
        # Advance clock past offer_expires_at; run ops.
        advance_clock_to_iso(
            scenario["marina"]["id"], "2024-04-17T00:00:00.000Z",
        )
        from test_helpers import run_ops
        run_ops(scenario["marina"]["id"])
        # Read back through the GET endpoint — we don't have a direct
        # GET for transfer requests, so observe via attempting to
        # accept after expiry — should be ERR_INVALID_STATE.
        resp = api.accept_transfer_request(
            scenario["marina"]["id"], tr["id"],
            __import__("test_helpers").make_boater_headers(
                scenario["boater"]["id"],
            ),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
