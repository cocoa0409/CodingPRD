"""Dispute, adjust, and void lifecycle.

PRD §3.10 governs the SETTLED → DISPUTED → SETTLED loop and the
ACTIVE → VOIDED escape valve.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    adjust_payload,
    advance_clock,
    create_funded_rider,
    dispute_payload,
    get_rider,
    get_ride,
    make_rider_headers,
    settle_simple_standard_ride,
    setup_basic_ride_scenario,
    start_ride,
    validate_error,
    validate_success,
    void_ride,
    ADMIN,
    OPERATOR,
)


class TestDispute:
    def test_dispute_settled_ride_succeeds(self, api):
        """PRD §3.10: 'On success the ride advances SETTLED → DISPUTED.'"""
        from test_helpers import dispute_ride
        ctx = settle_simple_standard_ride(duration_minutes=10)
        disputed = dispute_ride(ctx["ride"], rider_id=ctx["rider"]["id"])
        assert disputed["status"] == "DISPUTED", (
            f"PRD §3.10: SETTLED → DISPUTED, got {disputed['status']}"
        )

    def test_dispute_active_ride_rejected(self, api):
        """PRD §3.10: 'The ride must currently be SETTLED (otherwise
        ERR_RIDE_NOT_SETTLED).'"""
        ctx = setup_basic_ride_scenario(wallet_balance_cents=10000)
        ride = start_ride(ctx["rider"], ctx["bike"])
        resp = api.dispute_ride(
            ride["id"], dispute_payload(reason="x"),
            make_rider_headers(ctx["rider"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RIDE_NOT_SETTLED.value, 409)

    def test_dispute_outside_window_rejected(self, api):
        """PRD §3.10: 'Past that window the dispute is rejected with
        ERR_DISPUTE_WINDOW_CLOSED.'"""
        ctx = settle_simple_standard_ride(duration_minutes=10)
        # Advance clock by more than 1440 minutes past end
        advance_clock(1441)
        resp = api.dispute_ride(
            ctx["ride"]["id"], dispute_payload(reason="late"),
            make_rider_headers(ctx["rider"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value, 409)

    def test_dispute_no_money_movement(self, api):
        """PRD §3.10: 'No money moves at this step.'"""
        from test_helpers import dispute_ride
        ctx = settle_simple_standard_ride(duration_minutes=10)
        rider_before = get_rider(ctx["rider"]["id"])
        dispute_ride(ctx["ride"], rider_id=ctx["rider"]["id"])
        rider_after = get_rider(ctx["rider"]["id"])
        assert (rider_after["wallet_balance_cents"]
                == rider_before["wallet_balance_cents"]), (
            "PRD §3.10: 'No money moves at this step.'"
        )


class TestAdjust:
    def test_adjust_credits_difference_back_to_wallet(self, api):
        """PRD §3.10: 'On success the difference (current final_fare_cents
        minus new_final_fare_cents) is credited back to the rider's
        wallet_balance_cents.'"""
        from test_helpers import dispute_ride, adjust_ride
        ctx = settle_simple_standard_ride(duration_minutes=10)
        # Settled fare = 300
        wallet_after_settle = get_rider(ctx["rider"]["id"])["wallet_balance_cents"]
        dispute_ride(ctx["ride"], rider_id=ctx["rider"]["id"])
        adjust_ride(ctx["ride"]["id"], new_final_fare_cents=100)
        # Refund = 300 - 100 = 200
        wallet_final = get_rider(ctx["rider"]["id"])["wallet_balance_cents"]
        assert wallet_final == wallet_after_settle + 200, (
            f"PRD §3.10: refund = 300 - 100 = 200, "
            f"wallet {wallet_after_settle} → {wallet_final}"
        )

    def test_adjust_updates_final_fare_cents(self, api):
        """PRD §3.10: 'the ride's final_fare_cents is updated to the new
        value.'"""
        from test_helpers import dispute_ride, adjust_ride
        ctx = settle_simple_standard_ride(duration_minutes=10)
        dispute_ride(ctx["ride"], rider_id=ctx["rider"]["id"])
        adjusted = adjust_ride(ctx["ride"]["id"], new_final_fare_cents=100)
        assert adjusted["final_fare_cents"] == 100
        assert adjusted["status"] == "SETTLED", (
            "PRD §3.10: 'the ride moves DISPUTED → SETTLED'"
        )

    def test_adjust_settlement_variant_unchanged(self, api):
        """PRD §3.10: 'settlement_variant is unchanged.'"""
        from test_helpers import dispute_ride, adjust_ride
        # PER_MINUTE variant ride
        ctx = settle_simple_standard_ride(duration_minutes=10)
        original_variant = ctx["ride"]["settlement_variant"]
        dispute_ride(ctx["ride"], rider_id=ctx["rider"]["id"])
        adjusted = adjust_ride(ctx["ride"]["id"], new_final_fare_cents=50)
        assert adjusted["settlement_variant"] == original_variant, (
            f"PRD §3.10: settlement_variant unchanged, "
            f"was {original_variant}, now {adjusted['settlement_variant']}"
        )

    def test_adjust_exceeding_original_fare_rejected(self, api):
        """PRD §3.10: 'new_final_fare_cents must not be greater than
        the ride's current final_fare_cents — fare cannot be increased
        through adjustment (otherwise ERR_ADJUSTMENT_EXCEEDS_FARE).'"""
        from test_helpers import dispute_ride
        ctx = settle_simple_standard_ride(duration_minutes=10)
        dispute_ride(ctx["ride"], rider_id=ctx["rider"]["id"])
        original = ctx["ride"]["final_fare_cents"]  # 300
        resp = api.adjust_ride(
            ctx["ride"]["id"],
            adjust_payload(new_final_fare_cents=original + 1),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_FARE.value, 422)

    def test_adjust_undisputed_ride_rejected(self, api):
        """PRD §3.10: 'The ride must be DISPUTED (otherwise
        ERR_RIDE_NOT_DISPUTED).'"""
        ctx = settle_simple_standard_ride(duration_minutes=10)
        resp = api.adjust_ride(
            ctx["ride"]["id"],
            adjust_payload(new_final_fare_cents=50),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_RIDE_NOT_DISPUTED.value, 409)


class TestVoid:
    def test_void_active_ride_zeroes_fare(self, api):
        """PRD §3.10: 'On success the ride moves ACTIVE → VOIDED,
        final_fare_cents is set to 0, the bike returns to AVAILABLE,
        and no money moves at all.'"""
        ctx = setup_basic_ride_scenario(wallet_balance_cents=10000)
        ride = start_ride(ctx["rider"], ctx["bike"])
        voided = void_ride(ride["id"])
        assert voided["status"] == "VOIDED"
        assert voided["final_fare_cents"] == 0
        from test_helpers import get_bike
        bike = get_bike(ctx["bike"]["id"])
        assert bike["status"] == "AVAILABLE"
        rider_after = get_rider(ctx["rider"]["id"])
        assert rider_after["wallet_balance_cents"] == 10000, (
            "PRD §3.10: 'no money moves at all'"
        )

    def test_void_non_active_ride_rejected(self, api):
        """PRD §3.10: 'The ride must be ACTIVE (otherwise
        ERR_RIDE_NOT_ACTIVE).'"""
        ctx = settle_simple_standard_ride(duration_minutes=10)
        resp = api.void_ride(ctx["ride"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RIDE_NOT_ACTIVE.value, 409)
