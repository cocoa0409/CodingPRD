"""Coupon minting, validity, exhaustion (PRD §3.8)."""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    assert_coupon,
    create_coupon_payload,
    iso_utc,
    make_member_headers,
    mint_coupon,
    setup_active_member_with_subscription,
    validate_error,
    validate_success,
)


class TestCouponCreation:

    def test_mint_promotional_coupon(self, api):
        """PRD §3.8: "Promotional coupons are minted by a BillingAdmin through the
        coupons endpoint. Each coupon carries a human-typed code (uppercase A–Z
        and 0–9, length six to twelve characters, unique across the chain), a
        kind of PERCENT_OFF, FIXED_OFF_CENTS, or REFERRAL_REWARD, a value (percent
        zero through one hundred for PERCENT_OFF; cents for FIXED_OFF_CENTS or
        REFERRAL_REWARD), an applicable_to enumeration of SUBSCRIPTION, BOOKING,
        or BOTH..."

        Claim: a freshly minted promotional coupon is ACTIVE with
        tied_to_member_id=null and redemption_count=0.
        """
        coupon = mint_coupon(
            kind="PERCENT_OFF", value=15, applicable_to="BOTH", max_redemptions=10
        )
        assert_coupon(coupon)
        assert coupon["status"] == "ACTIVE"
        assert coupon["redemption_count"] == 0
        # PRD §3.8: "promotional coupons have a null tied_to_member_id."
        assert coupon["tied_to_member_id"] is None


class TestCouponValidity:

    def test_redeem_before_valid_from_rejected(self, api):
        """PRD §3.6: "the coupon must exist, its status must be ACTIVE, the present
        clock must fall in [valid_from, valid_until) (half-open), redemption_count
        must be strictly less than max_redemptions, and applicable_to must match
        the booking context (BOOKING or BOTH); failure surfaces as ERR_COUPON_INVALID."

        Claim: using a coupon whose valid_from is in the future → ERR_COUPON_INVALID
        on a booking attempt.
        """
        from test_helpers import setup_basic_scenario, create_booking_payload

        # Create a coupon valid only in the far future.
        future_from = iso_utc(datetime.now(timezone.utc) + timedelta(days=30))
        future_until = iso_utc(datetime.now(timezone.utc) + timedelta(days=60))
        coupon = mint_coupon(
            kind="PERCENT_OFF",
            value=15,
            applicable_to="BOTH",
            max_redemptions=5,
            valid_from=future_from,
            valid_until=future_until,
        )
        scen = setup_basic_scenario(state_code="CA", capacity=5, starts_in_hours=48)
        member = scen["member"]
        payload = create_booking_payload(
            booking_kind="GROUP_CLASS",
            class_session_id=scen["class_session"]["id"],
            starts_at=scen["class_session"]["starts_at"],
            ends_at=scen["class_session"]["ends_at"],
            applied_coupon_id=coupon["id"],
        )
        res = api.create_booking(member["id"], payload, make_member_headers(member["id"]))
        validate_error(res, "ERR_COUPON_INVALID")

    def test_redeem_with_wrong_applicable_to_rejected(self, api):
        """PRD §3.6: "applicable_to must match the booking context (BOOKING or
        BOTH); failure surfaces as ERR_COUPON_INVALID."

        Claim: a SUBSCRIPTION-only coupon used at booking time → ERR_COUPON_INVALID.
        """
        from test_helpers import setup_basic_scenario, create_booking_payload

        coupon = mint_coupon(
            kind="PERCENT_OFF",
            value=15,
            applicable_to="SUBSCRIPTION",  # NOT booking
            max_redemptions=5,
        )
        scen = setup_basic_scenario(state_code="CA", capacity=5, starts_in_hours=48)
        member = scen["member"]
        payload = create_booking_payload(
            booking_kind="GROUP_CLASS",
            class_session_id=scen["class_session"]["id"],
            starts_at=scen["class_session"]["starts_at"],
            ends_at=scen["class_session"]["ends_at"],
            applied_coupon_id=coupon["id"],
        )
        res = api.create_booking(member["id"], payload, make_member_headers(member["id"]))
        validate_error(res, "ERR_COUPON_INVALID")
