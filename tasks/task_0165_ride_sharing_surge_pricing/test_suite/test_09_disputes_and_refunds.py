"""Disputes: file → approve / reject; compensating earnings adjustment."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PLATFORM_FEE_RATE,
    approve_dispute,
    assert_dispute,
    create_completed_ride,
    create_dispute_payload,
    create_open_dispute,
    create_requested_ride,
    create_rider,
    expected_earnings_clawback,
    get_dispute,
    get_driver,
    get_ride,
    get_rider,
    make_rider_headers,
    reject_dispute,
    round_half_up_int,
    setup_completed_ride_with_known_fare,
    setup_disputed_ride,
    setup_grid_with_supply,
    setup_two_hop_refund_cascade,
    validate_error,
    validate_success,
)


# ===========================================================================
# Dispute creation — PRD §3.7.
# ===========================================================================
class TestDisputeCreate:

    def test_create_dispute_returns_open_and_marks_ride_disputed(self):
        """PRD §3.7: "Creating the dispute has cross-entity side
        effects: a new Dispute is written in OPEN status with the
        rider's id copied to the dispute's own rider_id field (for
        ownership checks downstream) and approved_refund_cents and
        resolved_at left null; the underlying ride's status moves from
        COMPLETED to DISPUTED."
        """
        scenario = setup_completed_ride_with_known_fare(distance_km=5.0)
        # final_fare_cents == 850 in this scenario.
        dispute = create_open_dispute(
            scenario["ride"]["id"], scenario["rider"]["id"],
            requested_refund_cents=300, reason_code="OVERCHARGE",
        )
        assert dispute["status"] == "OPEN"
        assert dispute["rider_id"] == scenario["rider"]["id"]
        assert dispute["approved_refund_cents"] is None
        assert dispute["resolved_at"] is None
        # Ride moved to DISPUTED.
        ride_after = get_ride(scenario["ride"]["id"])
        assert ride_after["status"] == "DISPUTED"

    def test_create_dispute_against_non_completed_ride_invalid_state(self,
                                                                     api):
        """PRD §2.9 (seventh): state preconditions yield
        ERR_INVALID_STATE.
        PRD §3.7: "A Rider may file a dispute on a COMPLETED ride."

        Ride in ON_TRIP must reject with ERR_INVALID_STATE.
        # difficulty: cross_entity_state_dependency/dispute_create_requires_ride_completed_pair
        """
        from test_helpers import create_on_trip_ride
        grid, _ = setup_grid_with_supply(num_drivers=1)
        rider = create_rider()
        ride, _ = create_on_trip_ride(rider["id"], grid["code"])
        resp = api.create_dispute(
            create_dispute_payload(
                ride_id=ride["id"], requested_refund_cents=100,
            ),
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_duplicate_open_dispute_rejected(self, api):
        """PRD §3.7: "Each ride may host at most one dispute over its
        lifetime — an attempt to file a second when an existing OPEN
        or APPROVED dispute is already attached yields
        ERR_DISPUTE_ALREADY_EXISTS."
        """
        scenario = setup_disputed_ride(distance_km=5.0,
                                       requested_refund_cents=100)
        resp = api.create_dispute(
            create_dispute_payload(
                ride_id=scenario["ride"]["id"],
                requested_refund_cents=50,
            ),
            make_rider_headers(scenario["rider"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_EXISTS.value)

    def test_refund_exceeds_fare_rejected(self, api):
        """PRD §3.7: "the requested_refund_cents (strictly greater
        than zero and at most the ride's final_fare_cents, otherwise
        ERR_REFUND_EXCEEDS_FARE)."
        """
        scenario = setup_completed_ride_with_known_fare(distance_km=5.0)
        # final_fare_cents == 850; request 9999 → exceeds.
        resp = api.create_dispute(
            create_dispute_payload(
                ride_id=scenario["ride"]["id"],
                requested_refund_cents=9_999,
            ),
            make_rider_headers(scenario["rider"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_FARE.value)

    def test_refund_zero_rejected(self, api):
        """PRD §3.7: "the requested_refund_cents (strictly greater
        than zero ... otherwise ERR_REFUND_EXCEEDS_FARE)."

        PRD ties both <=0 and >fare to the same error_id.
        """
        scenario = setup_completed_ride_with_known_fare(distance_km=5.0)
        resp = api.create_dispute(
            create_dispute_payload(
                ride_id=scenario["ride"]["id"],
                requested_refund_cents=0,
            ),
            make_rider_headers(scenario["rider"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_FARE.value)


# ===========================================================================
# Approve — refund credit + compensating earnings adjustment.
# ===========================================================================
class TestDisputeApprove:

    def test_approve_sets_status_and_resolved(self):
        """PRD §3.7: "Approval sets Dispute.status to APPROVED and
        writes approved_refund_cents ... the dispute's resolved_at is
        stamped to the current server time."
        """
        scenario = setup_disputed_ride(distance_km=5.0,
                                       requested_refund_cents=300)
        approved = approve_dispute(scenario["dispute"]["id"])
        assert approved["status"] == "APPROVED"
        assert approved["resolved_at"] is not None

    def test_approve_defaults_to_requested_when_amount_omitted(self):
        """PRD §3.7: "if omitted, the approved amount defaults to the
        dispute's requested_refund_cents."
        """
        scenario = setup_disputed_ride(distance_km=5.0,
                                       requested_refund_cents=300)
        approved = approve_dispute(scenario["dispute"]["id"],
                                   approved_refund_cents=None)
        assert approved["approved_refund_cents"] == 300

    def test_approve_credits_rider_wallet(self):
        """PRD §3.7: "Approval then has three further side effects: the
        rider's wallet_balance_cents is incremented by
        approved_refund_cents".
        # difficulty: transitive_cascade/refund_cascade_two_hops
        """
        scenario = setup_disputed_ride(distance_km=5.0,
                                       requested_refund_cents=300)
        rider_id = scenario["rider"]["id"]
        # Wallet at 0 before approve.
        r_before = get_rider(rider_id)
        assert r_before["wallet_balance_cents"] == 0
        approve_dispute(scenario["dispute"]["id"])
        r_after = get_rider(rider_id)
        assert r_after["wallet_balance_cents"] == 300

    def test_approve_clawbacks_driver_earnings(self):
        """PRD §3.7: "the driver's total_earnings_cents is decremented
        by the driver-share equivalent of the refund — that is, the
        approved_refund_cents multiplied by the quantity one minus the
        PLATFORM_FEE_RATE, rounded half-up to an integer cent, clamped
        so that total_earnings_cents never falls below zero (this is
        the compensating earnings adjustment)".

        With approved=300 → clawback = round_half_up(300*0.80) = 240.
        # difficulty: transitive_cascade/refund_cascade_two_hops
        # difficulty: compensating_invariant/refund_money_conservation_invariant
        """
        scenario = setup_disputed_ride(distance_km=5.0,
                                       requested_refund_cents=300)
        driver_id = scenario["driver"]["id"]
        d_before = get_driver(driver_id)
        # After single ride with final=850 → earnings 680.
        assert d_before["total_earnings_cents"] == 680
        approve_dispute(scenario["dispute"]["id"])
        d_after = get_driver(driver_id)
        # round_half_up(300 * 0.80) = 240; 680 - 240 = 440.
        assert d_after["total_earnings_cents"] == 440, (
            f"PRD §3.7: clawback = round_half_up(300*0.80)=240, so "
            f"680 - 240 = 440. Got {d_after['total_earnings_cents']}."
        )

    def test_approve_moves_ride_to_refunded(self):
        """PRD §3.7: "the ride's status advances from DISPUTED to
        REFUNDED".
        # difficulty: transitive_cascade/refund_cascade_two_hops
        """
        scenario = setup_disputed_ride(distance_km=5.0,
                                       requested_refund_cents=300)
        approve_dispute(scenario["dispute"]["id"])
        ride_after = get_ride(scenario["ride"]["id"])
        assert ride_after["status"] == "REFUNDED"

    def test_approve_with_amount_exceeding_requested_rejected(self, api,
                                                              dispute_ops_headers):
        """PRD §3.7: "it must not exceed the dispute's
        requested_refund_cents, otherwise ERR_REFUND_EXCEEDS_REQUEST".
        """
        scenario = setup_disputed_ride(distance_km=5.0,
                                       requested_refund_cents=300)
        resp = api.approve_dispute(
            scenario["dispute"]["id"], dispute_ops_headers,
            {"approved_refund_cents": 500},
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_REQUEST.value)


# ===========================================================================
# Reject — symmetric but no compensating drift.
# ===========================================================================
class TestDisputeReject:

    def test_reject_reverts_ride_to_completed(self):
        """PRD §3.7: "Rejection is symmetric in shape but undoes the
        dispute's claim. The dispute's status is set to REJECTED, the
        ride's status reverts from DISPUTED to COMPLETED (the prior
        state), and the dispute's resolved_at is stamped to the
        current server time."
        # difficulty: non_linear_state_machine/ride_dispute_revert_cycle
        """
        scenario = setup_disputed_ride(distance_km=5.0,
                                       requested_refund_cents=200)
        reject_dispute(scenario["dispute"]["id"])
        ride_after = get_ride(scenario["ride"]["id"])
        assert ride_after["status"] == "COMPLETED", (
            "PRD §3.7: rejection reverts the ride to COMPLETED."
        )
        dispute_after = get_dispute(scenario["dispute"]["id"])
        assert dispute_after["status"] == "REJECTED"
        assert dispute_after["resolved_at"] is not None

    def test_reject_does_not_drift_wallet_or_earnings(self):
        """PRD §3.7: "There is no compensating drift on either the
        rider's wallet_balance_cents or the driver's
        total_earnings_cents on rejection."
        """
        scenario = setup_disputed_ride(distance_km=5.0,
                                       requested_refund_cents=200)
        r_before = get_rider(scenario["rider"]["id"])
        d_before = get_driver(scenario["driver"]["id"])
        reject_dispute(scenario["dispute"]["id"])
        r_after = get_rider(scenario["rider"]["id"])
        d_after = get_driver(scenario["driver"]["id"])
        assert r_after["wallet_balance_cents"] == r_before["wallet_balance_cents"]
        assert d_after["total_earnings_cents"] == d_before["total_earnings_cents"]


# ===========================================================================
# Money conservation invariant.
# ===========================================================================
class TestRefundMoneyConservation:

    def test_refund_conserves_total_amount(self):
        """PRD §3.7: "the rider's wallet_balance_cents is incremented
        by approved_refund_cents; the driver's total_earnings_cents is
        decremented by the driver-share equivalent of the refund —
        that is, the approved_refund_cents multiplied by the quantity
        one minus the PLATFORM_FEE_RATE".

        Conserved quantity #1 — system money flow. The
        approved_refund_cents (total leaving the platform's collected
        fare) splits across rider wallet and a driver clawback such
        that delta_wallet == approved and -delta_driver ==
        round_half_up(approved*(1-PLATFORM_FEE_RATE)).
        # difficulty: compensating_invariant/refund_money_conservation_invariant
        """
        # Setup specifically with final=1000 to get a clean 500 refund.
        # PRD §3.7 setup: "final_fare_cents=1000, driver_earnings_cents
        # =800". To get a ride with final=1000 we need
        # base * 1.00 = 1000 → base=1000. base = 250 + round(distance*120)
        # = 1000 → round(distance*120) = 750 → distance = 6.25.
        scenario = setup_completed_ride_with_known_fare(distance_km=6.25)
        ride = scenario["ride"]
        # base=250+750=1000, final=1000, earnings=800.
        assert ride["final_fare_cents"] == 1000
        # File and approve a 500 refund.
        dispute = create_open_dispute(
            ride["id"], scenario["rider"]["id"],
            requested_refund_cents=500,
        )
        approve_dispute(dispute["id"], approved_refund_cents=500)
        # delta_wallet = +500; delta_driver = -round_half_up(500*0.80)
        # = -400.
        r_after = get_rider(scenario["rider"]["id"])
        d_after = get_driver(scenario["driver"]["id"])
        assert r_after["wallet_balance_cents"] == 500
        assert d_after["total_earnings_cents"] == 800 - 400
