"""Billing computation, payment, refund, and subscription credits.

Covers PRD §3.7 (provisional and final variants, subscription deduction,
refund).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    PER_SWAP_BASE_CENTS,
    SUBSCRIPTION_DEDUCTION_BASIC,
    SUBSCRIPTION_DEDUCTION_PREMIUM,
    TOU_RATE_SHOULDER,
    book_reservation,
    drive_swap_to_completed,
    find_billing_record_for_swap,
    make_admin_headers,
    make_member_headers,
    make_operator_headers,
    pay_billing,
    refund_billing,
    refund_payload,
    setup_basic_scene,
    validate_error,
    validate_success,
)


class TestBillingFormula:
    def test_amount_due_baseline_shoulder(self, api):
        """PRD §3.7: "per_swap_base_cents, is the constant five hundred
        cents. The SOC delta is the incoming SOC minus the outgoing SOC,
        floored at zero ... energy delivered ... SOC delta divided by one
        hundred and then multiplied by the battery model's
        rated_capacity_kwh ... time-of-use rate in cents per kilowatt-
        hour is forty for PEAK, twenty-five for SHOULDER, and fifteen for
        OFF_PEAK ... soc_diff_cents, is the energy delivered multiplied
        by the time-of-use rate multiplied by the markup factor 1.20,
        with the product rounded half-up to a whole cent ...
        tou_pass_through_cents, is the energy delivered multiplied by the
        time-of-use rate at a flat 1.00 multiplier ... amount_due_cents,
        is the subtotal minus the subscription deduction, floored at
        zero".

        Claim (SHOULDER, rated 50 kWh, outgoing 20, incoming 80,
        subscription NONE):
          soc_delta = 60; energy_kwh = 0.60 * 50 = 30
          soc_diff = round(30 * 25 * 1.20) = 900
          tou_pass = round(30 * 25 * 1.00) = 750
          subtotal = 500 + 900 + 750 = 2150
          amount_due_cents = 2150  (no deduction)
        """
        scene = setup_basic_scene(
            tou_zone="SHOULDER", rated_capacity_kwh=50.0,
            member_existing_installed=True,
            member_subscription_tier="NONE",
            member_subscription_swaps_remaining=0,
        )
        # Set held battery soc_pct to 80 (default in setup_basic_scene).
        res = book_reservation(scene)
        se = drive_swap_to_completed(scene, res, outgoing_soc_pct=20.0)
        br = find_billing_record_for_swap(
            scene, se["id"], scene["member"]["id"],
        )
        assert br["per_swap_base_cents"] == 500
        assert br["soc_diff_cents"] == 900
        assert br["tou_pass_through_cents"] == 750
        assert br["amount_due_cents"] == 2150
        assert br["subscription_deduction_cents"] == 0

    def test_soc_delta_floor_zero(self, api):
        """PRD §3.7: "if the incoming SOC is less than or equal to the
        outgoing SOC, no energy was delivered and the delta is zero."

        Claim: outgoing=90, incoming=80 → soc_diff_cents=0 and
        tou_pass_through_cents=0; amount_due_cents = per_swap_base = 500.
        """
        scene = setup_basic_scene(
            tou_zone="SHOULDER", rated_capacity_kwh=50.0,
            member_existing_installed=True,
        )
        res = book_reservation(scene)
        # held was created with soc_pct=80; outgoing inspection > 80
        # forces delta floor to 0.
        se = drive_swap_to_completed(scene, res, outgoing_soc_pct=90.0)
        br = find_billing_record_for_swap(
            scene, se["id"], scene["member"]["id"],
        )
        assert br["soc_diff_cents"] == 0
        assert br["tou_pass_through_cents"] == 0
        assert br["amount_due_cents"] == PER_SWAP_BASE_CENTS


class TestSubscriptionDeduction:
    def test_basic_subscription_deducts_500(self, api):
        """PRD §3.7: "five hundred cents for BASIC ... and it is applied
        only when the member's subscription_swaps_remaining is strictly
        greater than zero ... When the counter is zero, the deduction is
        zero regardless of tier."

        Claim: BASIC tier with subscription_swaps_remaining=1 →
        subscription_deduction_cents == 500; subscription_swaps_remaining
        decremented to 0.
        """
        scene = setup_basic_scene(
            tou_zone="SHOULDER", rated_capacity_kwh=50.0,
            member_existing_installed=True,
            member_subscription_tier="BASIC",
            member_subscription_swaps_remaining=1,
        )
        res = book_reservation(scene)
        se = drive_swap_to_completed(scene, res, outgoing_soc_pct=20.0)
        br = find_billing_record_for_swap(
            scene, se["id"], scene["member"]["id"],
        )
        assert br["subscription_deduction_cents"] == 500
        # subtotal 2150 - 500 = 1650.
        assert br["amount_due_cents"] == 1650
        # Member counter decremented.
        m = api.get_member(
            scene["member"]["id"],
            make_member_headers(scene["member"]["id"]),
        ).json()["data"]
        assert m["subscription_swaps_remaining"] == 0

    def test_subscription_zero_credits_no_deduction(self, api):
        """PRD §3.7: "When the counter is zero, the deduction is zero
        regardless of tier."

        Claim: PREMIUM tier with subscription_swaps_remaining=0 →
        subscription_deduction_cents == 0.
        """
        scene = setup_basic_scene(
            tou_zone="SHOULDER", rated_capacity_kwh=50.0,
            member_existing_installed=True,
            member_subscription_tier="PREMIUM",
            member_subscription_swaps_remaining=0,
        )
        res = book_reservation(scene)
        se = drive_swap_to_completed(scene, res, outgoing_soc_pct=20.0)
        br = find_billing_record_for_swap(
            scene, se["id"], scene["member"]["id"],
        )
        assert br["subscription_deduction_cents"] == 0


class TestPaymentAndRefund:
    def test_pay_billing_moves_to_paid(self, api):
        """PRD §3.7: "The member can pay it, moving payment_status from
        PENDING to PAID".

        Claim: pay on PENDING billing → payment_status='PAID'.
        """
        scene = setup_basic_scene(member_existing_installed=True)
        res = book_reservation(scene)
        se = drive_swap_to_completed(scene, res, outgoing_soc_pct=20.0)
        br = find_billing_record_for_swap(
            scene, se["id"], scene["member"]["id"],
        )
        paid = pay_billing(scene["member"]["id"], br["id"])
        assert paid["payment_status"] == "PAID"

    def test_full_refund_restores_subscription_credit(self, api):
        """PRD §3.7: "If the refund is a full refund — refund_cents
        equals amount_due_cents — and a subscription_deduction_cents was
        applied at swap-complete, the platform restores the member's
        subscription_swaps_remaining by adding one to it".

        Claim: complete swap with BASIC + 1 credit → credit drops to 0;
        after full refund, credit restored to 1.
        """
        scene = setup_basic_scene(
            tou_zone="SHOULDER", rated_capacity_kwh=50.0,
            member_existing_installed=True,
            member_subscription_tier="BASIC",
            member_subscription_swaps_remaining=1,
        )
        res = book_reservation(scene)
        se = drive_swap_to_completed(scene, res, outgoing_soc_pct=20.0)
        br = find_billing_record_for_swap(
            scene, se["id"], scene["member"]["id"],
        )
        # Pay first; PRD says refund applies to PAID record.
        pay_billing(scene["member"]["id"], br["id"])
        refunded = refund_billing(
            br["id"], refund_cents=br["amount_due_cents"],
        )
        assert refunded["payment_status"] == "REFUNDED"
        m = api.get_member(
            scene["member"]["id"],
            make_member_headers(scene["member"]["id"]),
        ).json()["data"]
        assert m["subscription_swaps_remaining"] == 1, (
            "PRD §3.7: full refund restores the consumed credit"
        )

    def test_partial_refund_does_not_restore_credit(self, api):
        """PRD §3.7: "partial refunds do not restore the credit."

        Claim: partial refund (< amount_due_cents) → subscription credit
        stays at 0.
        """
        scene = setup_basic_scene(
            tou_zone="SHOULDER", rated_capacity_kwh=50.0,
            member_existing_installed=True,
            member_subscription_tier="BASIC",
            member_subscription_swaps_remaining=1,
        )
        res = book_reservation(scene)
        se = drive_swap_to_completed(scene, res, outgoing_soc_pct=20.0)
        br = find_billing_record_for_swap(
            scene, se["id"], scene["member"]["id"],
        )
        pay_billing(scene["member"]["id"], br["id"])
        refunded = refund_billing(
            br["id"], refund_cents=br["amount_due_cents"] - 1,
        )
        assert refunded["payment_status"] == "REFUNDED"
        m = api.get_member(
            scene["member"]["id"],
            make_member_headers(scene["member"]["id"]),
        ).json()["data"]
        assert m["subscription_swaps_remaining"] == 0

    def test_refund_exceeding_paid_rejected(self, api, platform_admin_headers):
        """PRD §3.7: "refund_cents, which must be strictly greater than
        zero and at most equal to amount_due_cents; out-of-bounds values
        are rejected with ERR_REFUND_EXCEEDS_PAID."

        Claim: refund_cents = amount_due_cents + 1 → ERR_REFUND_EXCEEDS_PAID.
        """
        scene = setup_basic_scene(member_existing_installed=True)
        res = book_reservation(scene)
        se = drive_swap_to_completed(scene, res, outgoing_soc_pct=20.0)
        br = find_billing_record_for_swap(
            scene, se["id"], scene["member"]["id"],
        )
        pay_billing(scene["member"]["id"], br["id"])
        resp = api.refund_billing_record(
            br["id"], refund_payload(br["amount_due_cents"] + 1),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_PAID.value)

    def test_refund_zero_rejected(self, api, platform_admin_headers):
        """PRD §3.7: "refund_cents, which must be strictly greater than
        zero".

        Claim: refund_cents = 0 → ERR_REFUND_EXCEEDS_PAID 422.
        """
        scene = setup_basic_scene(member_existing_installed=True)
        res = book_reservation(scene)
        se = drive_swap_to_completed(scene, res, outgoing_soc_pct=20.0)
        br = find_billing_record_for_swap(
            scene, se["id"], scene["member"]["id"],
        )
        pay_billing(scene["member"]["id"], br["id"])
        resp = api.refund_billing_record(
            br["id"], refund_payload(0), platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_PAID.value)
