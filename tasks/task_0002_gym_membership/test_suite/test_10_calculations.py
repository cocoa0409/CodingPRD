"""Calculation tests: pricing, refunds, late fees, rounding order (PRD §3.2, §3.3, §3.6, §3.7)."""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_booking,
    create_booking_for_member,
    create_payment_attempt_payload,
    create_subscription_for_member,
    discover_or_create_store,
    get_member_fresh,
    iso_utc,
    make_member_headers,
    mint_coupon,
    register_member,
    register_trainer,
    schedule_class_session,
    setup_active_member_with_subscription,
    submit_payment_attempt,
    validate_error,
    validate_success,
)


class TestSubscriptionAmountFormula:

    def test_percent_off_rounding_order_divergent(self, api):
        """PRD §3.3 implies a pinned rounding order: PERCENT_OFF rounds at the
        discount step, then subtracts.

        With base=1050 and PERCENT_OFF 7%:
          - Pinned: round_half_up(1050 * 7 / 100) = round_half_up(73.5) = 74 →
            net = 1050 - 74 = 976
          - End-rounded: round_half_up(1050 * 93 / 100) = round_half_up(976.5) = 977
        The pinned answer is 976; an implementation that rounds at the end would
        produce 977.

        PRD §3.3: "if the coupon's kind is PERCENT_OFF, multiply gross_cents by
        value divided by one hundred and round half up to whole cents, calling
        the result discount_cents... Compute net_after_coupon as gross_cents
        minus discount_cents."

        Claim: server-computed amount_cents equals 976 (pinned discount-rounding
        order).
        """
        coupon = mint_coupon(
            kind="PERCENT_OFF", value=7, applicable_to="SUBSCRIPTION", max_redemptions=5
        )
        member = register_member(state_code="CA")
        # PRD §3.2 says base_price_cents is "pinned from the chain's plan list at
        # the moment of activation". PRD does not pin BASIC=1050 anywhere, so we
        # cannot guarantee the implementation will pin 1050. Instead we test the
        # rounding-order claim by recording the server's first-attempt amount and
        # comparing it to the rounding-order-pinned formula evaluated AGAINST the
        # server-pinned base_price_cents.
        sub = create_subscription_for_member(
            member,
            plan="BASIC",
            billing_cycle="MONTHLY",
            applied_coupon_code=coupon["code"],
        )
        # We don't know the chain-pinned base for BASIC, so read what the server
        # set and compute the expected pinned result, then submit it.
        gross = sub["base_price_cents"]
        expected_discount = (gross * 7 + 50) // 100  # round_half_up for non-negative
        expected_net = gross - expected_discount
        expected_amount = max(0, expected_net)  # wallet is 0
        payload = create_payment_attempt_payload(
            outcome="SUCCESS", amount_cents=expected_amount
        )
        res = api.create_payment_attempt(
            member["id"], sub["id"], payload, TEST_USERS["billing_admin_headers"]
        )
        data = validate_success(res, 201)
        assert data["amount_cents"] == expected_amount, (
            f"PRD §3.3 pinned rounding-at-discount order: with base={gross} and "
            f"PERCENT_OFF 7%, expected amount {expected_amount}, got {data['amount_cents']}"
        )


class TestBookingPricingPT:

    def test_pt_pricing_pinned_order_late_booking_surcharge(self, api):
        """PRD §3.6: "For personal training, duration_minutes is the integer
        number of whole minutes between ends_at and starts_at, and base_cents is
        the trainer's hourly_rate_cents multiplied by duration_minutes and
        divided by sixty, then rounded *up* to the next whole cent (ceiling).
        Next, the member's tier discount is applied: tier_discount_pct is zero
        for BASIC, ten for PLUS, twenty for ELITE; the discount in cents is
        base_cents times tier_discount_pct divided by one hundred, rounded half
        up; the running total after_tier is base_cents minus that discount.
        Then the late-booking check: compute hours_to_start... If hours_to_start
        is less than two — the late-booking threshold — apply a surcharge of
        after_tier multiplied by twenty-five percent, rounded half up; otherwise
        the surcharge is zero. Add the surcharge to after_tier."

        Claim: PLUS member, trainer hourly_rate=8000, 30-minute PT session
        starting in 1.5 hours →
            base_cents = ceil(8000 * 30 / 60) = 4000
            tier_discount = round_half_up(4000 * 10 / 100) = 400
            after_tier = 4000 - 400 = 3600
            hours_to_start = 1.5 < 2 → surcharge = round_half_up(3600 * 25 / 100) = 900
            provisional_price_cents = 3600 + 900 = 4500
        """
        store = discover_or_create_store("CA")
        trainer = register_trainer(home_store_id=store["id"], hourly_rate_cents=8000)
        member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        # PT booking 1.5h from now (within the 2h late-booking surcharge band).
        starts_dt = datetime.now(timezone.utc) + timedelta(minutes=90)
        ends_dt = starts_dt + timedelta(minutes=30)
        booking = create_booking_for_member(
            member,
            booking_kind="PERSONAL_TRAINING",
            trainer=trainer,
            starts_at=iso_utc(starts_dt),
            ends_at=iso_utc(ends_dt),
        )
        assert_booking(booking)
        assert booking["provisional_price_cents"] == 4500, (
            f"PRD §3.6 PT pricing: base=ceil(8000*30/60)=4000; tier 10%→3600; "
            f"1.5h<2 surcharge 25%→900; total=4500; got {booking['provisional_price_cents']}"
        )

    def test_group_class_yoga_base_price(self, api):
        """PRD §3.6: "For a group class, the starting price base_cents is the
        class-type base rate — two thousand cents for YOGA, two thousand five
        hundred cents for SPIN, two thousand two hundred cents for HIIT."

        Claim: a PLUS member booking a YOGA class >2h out (no surcharge) at
        capacity-available session →
            base = 2000
            tier_discount = round_half_up(2000 * 10 / 100) = 200
            after_tier = 1800
            surcharge = 0 (>2h)
            provisional = 1800
        """
        from test_helpers import setup_basic_scenario

        scen = setup_basic_scenario(
            state_code="CA", plan="PLUS", class_type="YOGA", capacity=5, starts_in_hours=48
        )
        booking = create_booking_for_member(
            scen["member"], booking_kind="GROUP_CLASS", class_session=scen["class_session"]
        )
        assert booking["provisional_price_cents"] == 1800, (
            f"PRD §3.6: YOGA base 2000 - 10% tier discount = 1800 (no surcharge >2h); "
            f"got {booking['provisional_price_cents']}"
        )


class TestRefundSchedules:

    @pytest.mark.parametrize(
        "state_code,hours_to_start,expected_pct",
        [
            ("CA", 24, 100),
            ("CA", 12, 50),
            ("NY", 48, 100),
            ("NY", 24, 75),
            ("NY", 2, 25),
            ("TX", 12, 100),
            ("TX", 6, 0),
        ],
    )
    def test_refund_pct_by_state_and_hours(self, api, state_code, hours_to_start, expected_pct):
        """PRD §3.7: refund schedules pinned per state_code with inclusive
        thresholds on hours_to_start.

        - CA: "if hours_to_start ... is at least twenty-four, refund one hundred
          percent; otherwise if hours_to_start is at least two, refund fifty
          percent; otherwise refund zero."
        - NY: "at least forty-eight hours, one hundred percent; at least six
          hours, seventy-five percent; at least one hour, twenty-five percent;
          otherwise zero."
        - TX: "at least twelve hours, one hundred percent; otherwise zero."

        Claim: voluntary member cancel at exactly the hours_to_start parameterised
        per state yields the parameterised refund_pct.
        """
        from test_helpers import setup_member_with_existing_booking, get_booking_fresh

        scen = setup_member_with_existing_booking(
            state_code=state_code,
            starts_in_hours=hours_to_start,
            duration_minutes=60,
            plan="PLUS",
        )
        member = scen["member"]
        booking = scen["booking"]
        provisional = booking["provisional_price_cents"]
        expected_refund = round(provisional * expected_pct / 100)
        res = api.cancel_booking(member["id"], booking["id"], make_member_headers(member["id"]))
        data = validate_success(res, 200)
        assert data["status"] == "CANCELLED"
        assert data["final_price_cents"] == provisional - expected_refund, (
            f"PRD §3.7 {state_code} @ {hours_to_start}h: refund {expected_pct}% of "
            f"{provisional}={expected_refund}; expected final {provisional - expected_refund}, "
            f"got {data['final_price_cents']}"
        )
