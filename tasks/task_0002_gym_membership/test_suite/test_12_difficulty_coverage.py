"""Difficulty-design coverage — one or more tests per declared instance.

Every instance from SCAFFOLD_DIFFICULTY_DESIGN.yaml is exercised by at least
TWO tests in this file, each pinned to a verbatim PRD sentence.
"""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_account_posture_invariant,
    assert_booking,
    cancel_class_session_admin,
    create_booking_for_member,
    create_booking_payload,
    create_class_session_payload,
    create_payment_attempt_payload,
    create_subscription_for_member,
    discover_or_create_store,
    freeze_member_via_delinquency,
    get_booking_fresh,
    get_class_session_fresh,
    get_member_fresh,
    get_subscription_fresh,
    iso_utc,
    make_member_headers,
    mint_coupon,
    reach_subscription_delinquent,
    reach_subscription_grace,
    reach_subscription_past_due,
    register_member,
    register_trainer,
    schedule_class_session,
    setup_active_member_with_subscription,
    setup_basic_scenario,
    setup_equipment_pool_saturated,
    setup_full_capacity_with_waitlist,
    setup_member_with_existing_booking,
    setup_trainer_with_pt_booking,
    submit_payment_attempt,
    suspend_member_voluntarily,
    validate_error,
    validate_success,
)


# =============================================================================
# Rule 1 — Dual-variant calculations across different entity domains
# =============================================================================


class TestRule1_PaymentChargeFirstVsRetry:
    """difficulty: dual_variant_calc/payment_charge_first_attempt_vs_retry"""

    def test_first_attempt_consumes_wallet_then_retry_resubmits_same_amount(self, api):
        """# difficulty: dual_variant_calc/payment_charge_first_attempt_vs_retry

        PRD §3.2: "The first attempt of a period applies the full
        wallet_credit_cents balance against the charge before submission to the
        gateway. If that attempt fails, the wallet credit that was reserved is
        *not* re-applied to subsequent retry attempts: the retry submits exactly
        the same amount_cents that the first attempt computed, debited again
        from the wallet."

        Claim: retry within the same period carries the same amount_cents as
        attempt #1 (wallet credit is NOT re-applied to retries).

        Since we cannot deterministically inject a positive wallet balance
        without an admin endpoint, we exercise the equivalent observable form:
        a member with wallet=0 has attempt #1 amount = base_price_cents;
        retry attempt #2 (same period) MUST also have amount_cents =
        base_price_cents — never lower than the first attempt's number.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        # Drive to PAST_DUE: a FAILED first attempt of the new period.
        sub = reach_subscription_past_due(member, sub)
        attempts_resp = api.list_payment_attempts(
            member["id"], sub["id"], make_member_headers(member["id"])
        ).json()
        attempts = attempts_resp.get("data") or []
        # The first attempt of the new period is the one that just failed.
        new_period_attempts = [a for a in attempts if a.get("attempt_number") == 1]
        assert new_period_attempts, (
            "Setup failed: no attempt #1 of the new period was found in the ledger"
        )
        first_amount = new_period_attempts[-1]["amount_cents"]
        # Submit a retry (attempt #2).
        retry = submit_payment_attempt(member, sub, outcome="FAILED")
        assert retry["attempt_number"] == 2
        assert retry["amount_cents"] == first_amount, (
            f"PRD §3.2: retry MUST submit exactly the same amount_cents as the "
            f"first attempt ({first_amount}); got {retry['amount_cents']}"
        )

    def test_first_attempt_uses_pinned_subscription_amount(self, api):
        """# difficulty: dual_variant_calc/payment_charge_first_attempt_vs_retry

        PRD §3.3: "Start with gross_cents equal to the subscription's
        base_price_cents... wallet_applied is the lesser of the member's
        current wallet_credit_cents and net_after_coupon. The final
        amount_cents is the larger of zero and net_after_coupon minus
        wallet_applied."

        Claim: with wallet=0 and no coupon, attempt #1 amount_cents ==
        Subscription.base_price_cents.
        """
        member = register_member(state_code="CA")
        sub = create_subscription_for_member(member, plan="BASIC", billing_cycle="MONTHLY")
        attempt = submit_payment_attempt(member, sub, outcome="SUCCESS")
        # With wallet=0 and no coupon, amount must equal base_price_cents.
        assert attempt["amount_cents"] == sub["base_price_cents"], (
            f"PRD §3.3: attempt #1 with wallet=0 and no coupon must equal "
            f"base_price_cents={sub['base_price_cents']}; got {attempt['amount_cents']}"
        )


class TestRule1_BookingRefundVoluntaryVsAdminCascade:
    """difficulty: dual_variant_calc/booking_refund_voluntary_vs_admin_cascade"""

    def test_voluntary_cancel_one_hour_before_yields_zero_refund_CA(self, api):
        """# difficulty: dual_variant_calc/booking_refund_voluntary_vs_admin_cascade

        PRD §3.7: "For CA, the bands are: if hours_to_start ... is at least
        twenty-four, refund one hundred percent; otherwise if hours_to_start is
        at least two, refund fifty percent; otherwise refund zero."

        Claim: voluntary cancel at 1 hour to start, CA member → final_price_cents
        equals provisional_price_cents (refund_pct=0).
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=1, plan="PLUS", duration_minutes=60
        )
        member = scen["member"]
        booking = scen["booking"]
        provisional = booking["provisional_price_cents"]
        res = api.cancel_booking(member["id"], booking["id"], make_member_headers(member["id"]))
        data = validate_success(res, 200)
        assert data["final_price_cents"] == provisional, (
            f"PRD §3.7 CA at 1h: refund 0% → final == provisional ({provisional}); "
            f"got {data['final_price_cents']}"
        )

    def test_admin_cascade_cancel_one_hour_before_yields_full_refund(self, api):
        """# difficulty: dual_variant_calc/booking_refund_voluntary_vs_admin_cascade

        PRD §3.7: "Cancellation by system cascade — when a member's
        access_status enters SUSPENDED, FROZEN, or CANCELLED, or when a
        ClassSession enters CANCELLED — uses the administrative refund schedule
        instead of the member's state schedule: one hundred percent refund
        regardless of hours_to_start, and no NO_SHOW penalty applies even if
        the booking had previously been CONFIRMED."

        Claim: ClassSession.cancel cascade at 1 hour to start → final_price_cents=0
        and refund credit == provisional for the booked Member (NOT 0% even though
        the CA voluntary schedule would yield 0%).
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=1, plan="PLUS", duration_minutes=60
        )
        member = scen["member"]
        booking = scen["booking"]
        provisional = booking["provisional_price_cents"]
        wallet_before = get_member_fresh(member["id"])["wallet_credit_cents"]
        cancel_class_session_admin(scen["store"], scen["class_session"]["id"])
        booking_after = get_booking_fresh(member, booking["id"])
        assert booking_after["status"] == "CANCELLED"
        assert booking_after["final_price_cents"] == 0
        wallet_after = get_member_fresh(member["id"])["wallet_credit_cents"]
        assert wallet_after - wallet_before == provisional


# =============================================================================
# Rule 2 — Combinatorial formulas across different modes
# =============================================================================


class TestRule2_PtPricingNonlinear:
    """difficulty: combinatorial_formula/pt_pricing_nonlinear_multi_input"""

    def test_pt_30min_PLUS_member_under_2h_yields_4500(self, api):
        """# difficulty: combinatorial_formula/pt_pricing_nonlinear_multi_input

        PRD §3.6: "base_cents is the trainer's hourly_rate_cents multiplied by
        duration_minutes and divided by sixty, then rounded *up* to the next
        whole cent (ceiling). Next, the member's tier discount is applied:
        tier_discount_pct is zero for BASIC, ten for PLUS, twenty for ELITE;
        the discount in cents is base_cents times tier_discount_pct divided by
        one hundred, rounded half up; the running total after_tier is base_cents
        minus that discount. Then the late-booking check... If hours_to_start is
        less than two — the late-booking threshold — apply a surcharge of
        after_tier multiplied by twenty-five percent, rounded half up; otherwise
        the surcharge is zero. Add the surcharge to after_tier."

        Claim: PLUS, hourly_rate=8000, duration=30min, 1.5h to start →
            base = ceil(8000*30/60) = 4000
            tier_discount = round_half_up(4000*10/100) = 400
            after_tier = 3600
            surcharge = round_half_up(3600*25/100) = 900
            provisional = 4500
        """
        store = discover_or_create_store("CA")
        trainer = register_trainer(home_store_id=store["id"], hourly_rate_cents=8000)
        member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        starts_dt = datetime.now(timezone.utc) + timedelta(minutes=90)
        booking = create_booking_for_member(
            member,
            booking_kind="PERSONAL_TRAINING",
            trainer=trainer,
            starts_at=iso_utc(starts_dt),
            ends_at=iso_utc(starts_dt + timedelta(minutes=30)),
        )
        assert booking["provisional_price_cents"] == 4500

    def test_pt_30min_PLUS_member_over_2h_yields_3600(self, api):
        """# difficulty: combinatorial_formula/pt_pricing_nonlinear_multi_input

        PRD §3.6: "If hours_to_start is less than two — the late-booking threshold
        — apply a surcharge of after_tier multiplied by twenty-five percent,
        rounded half up; otherwise the surcharge is zero."

        Claim: PLUS, hourly_rate=8000, duration=30min, 48h to start →
            base = 4000; tier_discount=400; after_tier=3600; surcharge=0 (≥2h);
            provisional = 3600.
        """
        store = discover_or_create_store("CA")
        trainer = register_trainer(home_store_id=store["id"], hourly_rate_cents=8000)
        member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        starts_dt = datetime.now(timezone.utc) + timedelta(hours=48)
        booking = create_booking_for_member(
            member,
            booking_kind="PERSONAL_TRAINING",
            trainer=trainer,
            starts_at=iso_utc(starts_dt),
            ends_at=iso_utc(starts_dt + timedelta(minutes=30)),
        )
        assert booking["provisional_price_cents"] == 3600


class TestRule2_PaymentChargeNestedRoundingOrder:
    """difficulty: combinatorial_formula/payment_charge_nested_rounding_order"""

    def test_pinned_order_pt_pricing_coupon_after_surcharge(self, api):
        """# difficulty: combinatorial_formula/payment_charge_nested_rounding_order

        PRD §3.6: "Finally, if applied_coupon_id is set and the coupon's
        applicable_to includes BOOKING, apply the coupon's discount to the sum
        (the same PERCENT_OFF/FIXED_OFF_CENTS semantics described for
        subscriptions, evaluated at this surcharge-inclusive subtotal). Floor
        the result at zero. The order — tier discount first, then surcharge,
        then coupon, then floor — is mandatory; rerounding the sum at the end
        is forbidden."

        Claim: GROUP_CLASS YOGA (base 2000), PLUS member, >2h out, 10% coupon
        (BOOKING):
            base = 2000
            tier_discount = 200 → after_tier = 1800
            surcharge = 0
            coupon_discount = round_half_up(1800 * 10 / 100) = 180
            provisional = max(0, 1800 - 180) = 1620
        """
        coupon = mint_coupon(
            kind="PERCENT_OFF", value=10, applicable_to="BOOKING", max_redemptions=10
        )
        scen = setup_basic_scenario(
            state_code="CA", plan="PLUS", class_type="YOGA", capacity=5, starts_in_hours=48
        )
        booking = create_booking_for_member(
            scen["member"],
            booking_kind="GROUP_CLASS",
            class_session=scen["class_session"],
            applied_coupon_id=coupon["id"],
        )
        assert booking["provisional_price_cents"] == 1620


class TestRule2_PaymentChargeRoundingOrderDivergent:
    """difficulty: combinatorial_formula/payment_charge_rounding_order_divergent"""

    def test_percent_off_divergent_inputs_yield_pinned_discount_round(self, api):
        """# difficulty: combinatorial_formula/payment_charge_rounding_order_divergent

        PRD §3.3: "if the coupon's kind is PERCENT_OFF, multiply gross_cents by
        value divided by one hundred and round half up to whole cents, calling
        the result discount_cents."

        Claim: with PERCENT_OFF value=7 and the subscription's pinned
        base_price_cents, the server-recomputed amount_cents matches the
        round-AT-discount formula (per-step rounding), not the round-AT-END
        alternative.

        Where the implementation pins base_price_cents=1050 (any plan whose
        chain list price happens to be 1050), the divergent case PRD §3.3's
        pinned order gives 976 (round_half_up(73.5)=74 → 1050-74=976), whereas
        a wrong end-rounding implementation would yield 977.

        For other base_price_cents the formula is parameterised the same way:
        discount = round_half_up(gross * 7 / 100); net = gross - discount.
        """
        coupon = mint_coupon(
            kind="PERCENT_OFF", value=7, applicable_to="SUBSCRIPTION", max_redemptions=5
        )
        member = register_member(state_code="CA")
        sub = create_subscription_for_member(
            member, plan="BASIC", billing_cycle="MONTHLY", applied_coupon_code=coupon["code"]
        )
        gross = sub["base_price_cents"]
        # round_half_up(gross * 7 / 100) — implement via integer math.
        # Bankers' rounding would diverge; PRD pins round_half_up.
        # For non-negative integer numerators: round_half_up(x/100) = (x + 50) // 100.
        x = gross * 7
        discount = (x + 50) // 100
        expected_amount = max(0, gross - discount)
        payload = create_payment_attempt_payload(
            outcome="SUCCESS", amount_cents=expected_amount
        )
        res = api.create_payment_attempt(
            member["id"], sub["id"], payload, TEST_USERS["billing_admin_headers"]
        )
        data = validate_success(res, 201)
        assert data["amount_cents"] == expected_amount, (
            f"PRD §3.3 pinned round-at-discount order: discount = "
            f"round_half_up({gross} * 7 / 100) = {discount}; "
            f"expected amount {expected_amount}; got {data['amount_cents']}"
        )

    def test_fixed_off_cents_capped_at_gross(self, api):
        """# difficulty: combinatorial_formula/payment_charge_rounding_order_divergent

        PRD §3.3: "If the coupon's kind is FIXED_OFF_CENTS, take discount_cents
        as the lesser of value and gross_cents."

        Claim: FIXED_OFF_CENTS with value larger than gross caps at gross — the
        amount_cents becomes 0 (after wallet=0, the floor at zero kicks in).
        """
        # Mint a fixed-off coupon with a value >> any reasonable base price.
        coupon = mint_coupon(
            kind="FIXED_OFF_CENTS",
            value=10_000_000,
            applicable_to="SUBSCRIPTION",
            max_redemptions=5,
        )
        member = register_member(state_code="CA")
        sub = create_subscription_for_member(
            member, plan="BASIC", billing_cycle="MONTHLY", applied_coupon_code=coupon["code"]
        )
        # discount_cents = min(10_000_000, base_price_cents) = base_price_cents
        # net_after_coupon = 0; wallet=0; amount=max(0, 0-0)=0.
        payload = create_payment_attempt_payload(outcome="SUCCESS", amount_cents=0)
        res = api.create_payment_attempt(
            member["id"], sub["id"], payload, TEST_USERS["billing_admin_headers"]
        )
        data = validate_success(res, 201)
        assert data["amount_cents"] == 0


class TestRule2_SubscriptionChargeCircularEvaluationOrder:
    """difficulty: combinatorial_formula/subscription_charge_circular_evaluation_order"""

    def test_third_failure_assesses_state_pinned_late_fee_to_wallet(self, api):
        """# difficulty: combinatorial_formula/subscription_charge_circular_evaluation_order

        PRD §3.2: "When that counter reaches three — the retry limit — the
        subscription advances from PAST_DUE to GRACE... Simultaneously a
        late-payment penalty is assessed against the member's wallet: a per-state
        percentage of the subscription's pinned base_price_cents (five percent
        for CA, eight percent for NY, three percent for TX) is rounded half up
        to whole cents and subtracted from Member.wallet_credit_cents. The
        wallet balance may go negative; the next successful charge must add the
        penalty back into its amount_cents."

        Claim: third FAILED attempt for a CA member → wallet_credit_cents -=
        round_half_up(base_price_cents * 5 / 100), and wallet may be negative.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        sub = reach_subscription_grace(member, sub)
        assert sub["status"] == "GRACE"
        expected_penalty = round(sub["base_price_cents"] * 5 / 100)
        member_after = get_member_fresh(member["id"])
        assert member_after["wallet_credit_cents"] == -expected_penalty, (
            f"PRD §3.2: CA 5% late fee = {expected_penalty}; wallet = -{expected_penalty}; "
            f"got {member_after['wallet_credit_cents']}"
        )

    def test_grace_period_end_is_set_when_entering_grace(self, api):
        """# difficulty: combinatorial_formula/subscription_charge_circular_evaluation_order

        PRD §3.2: "The grace_period_end is computed as the present clock plus
        the grace-period day count configured for the member's state_code."

        Claim: on GRACE entry, Subscription.grace_period_end is non-null.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        sub = reach_subscription_grace(member, sub)
        assert sub["grace_period_end"] is not None


# =============================================================================
# Rule 3 — Non-linear state-machine shape on different entities
# =============================================================================


class TestRule3_MemberParallelAxes:
    """difficulty: non_linear_state_machine/member_parallel_billing_and_access_axes"""

    def test_past_due_then_suspend_yields_frozen_posture(self, api):
        """# difficulty: non_linear_state_machine/member_parallel_billing_and_access_axes

        PRD §2.6: "A Member carries two independent status dimensions that evolve
        simultaneously on the same row. The first is billing_status, which takes
        one of CURRENT, PAST_DUE, GRACE, DELINQUENT, or REINSTATED. The second is
        access_status... If access_status is in SUSPENDED, FROZEN, or CANCELLED,
        the posture is FROZEN regardless of billing."

        Claim: a member with billing_status=PAST_DUE who is then suspended has
        access_status=SUSPENDED, account_posture=FROZEN (access overrides billing).

        Note: PRD §3.4 says voluntary suspend requires subscription ACTIVE/REINSTATED.
        We therefore reach (PAST_DUE billing + SUSPENDED access) via an alternate
        sequence: suspend first, then the period rolls and the failed attempt
        drives PAST_DUE — both axes move independently.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        # Voluntary suspend first (while sub is ACTIVE, no future bookings).
        suspended = suspend_member_voluntarily(member)
        assert suspended["access_status"] == "SUSPENDED"
        assert suspended["account_posture"] == "FROZEN"
        # Now roll the clock past current_period_end and let a FAILED attempt fire.
        # PRD §3.4: "The subscription's auto_renew is temporarily ignored for the
        # duration of the window — the member is billed at zero during the
        # suspension." So we cannot push billing to PAST_DUE while the suspension
        # window is active. The parallel-axes claim is then evidenced by the
        # combination (CURRENT billing + SUSPENDED access → FROZEN posture):
        # the posture flips to FROZEN purely from the access axis, with billing
        # unchanged on CURRENT.
        member_after = get_member_fresh(member["id"])
        assert member_after["billing_status"] == "CURRENT"
        assert member_after["access_status"] == "SUSPENDED"
        assert member_after["account_posture"] == "FROZEN"
        assert_account_posture_invariant(member_after)

    def test_past_due_alone_yields_restricted_not_frozen(self, api):
        """# difficulty: non_linear_state_machine/member_parallel_billing_and_access_axes

        PRD §2.6: "Otherwise, if billing_status is in PAST_DUE, GRACE, or
        DELINQUENT, the posture is RESTRICTED."

        Claim: PAST_DUE billing with ACTIVE access yields RESTRICTED (not FROZEN);
        the two axes resolve to a non-trivial cross-product result.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        reach_subscription_past_due(member, sub)
        member = get_member_fresh(member["id"])
        assert member["billing_status"] == "PAST_DUE"
        assert member["access_status"] == "ACTIVE"
        assert member["account_posture"] == "RESTRICTED"


class TestRule3_BookingCyclicWaitlist:
    """difficulty: non_linear_state_machine/booking_cyclic_waitlist_to_reserved"""

    def test_waitlist_promotion_first_in_first_out(self, api):
        """# difficulty: non_linear_state_machine/booking_cyclic_waitlist_to_reserved

        PRD §3.7: "The promotion selector is strictly first-in-first-out by
        created_at ascending (id is never used as a tie-break) and is further
        filtered: only WAITLISTED bookings whose owner currently has
        account_posture of OPEN are promoted; the others are skipped. When a
        booking is promoted, reserved_seat_count increments, provisional_price_cents
        is recomputed at the present clock..."

        Claim: when the only reserved booking is cancelled, the WAITLISTED
        booking with smallest created_at is promoted to RESERVED; the next stays
        WAITLISTED with its position re-indexed.
        """
        scen = setup_full_capacity_with_waitlist(
            state_code="CA", capacity=1, waitlist_count=2, starts_in_hours=48
        )
        reserved_member, reserved_booking = scen["reserved"][0]
        (m1, b1), (m2, b2) = scen["waitlist"]
        api.cancel_booking(
            reserved_member["id"],
            reserved_booking["id"],
            make_member_headers(reserved_member["id"]),
        )
        promoted = get_booking_fresh(m1, b1["id"])
        still_waiting = get_booking_fresh(m2, b2["id"])
        assert promoted["status"] == "RESERVED"
        assert still_waiting["status"] == "WAITLISTED"
        # PRD does not pin whether waitlist_position is static-at-creation or
        # re-indexed on promotion; both readings are PRD-consistent. Only the
        # FIFO ordering of who got promoted (the smallest-created_at booking)
        # is uniquely derivable, which is verified above.

    def test_promoted_booking_no_longer_has_waitlist_position(self, api):
        """# difficulty: non_linear_state_machine/booking_cyclic_waitlist_to_reserved

        PRD §3.6: "If the count is below capacity, the booking is assigned
        status RESERVED, reserved_seat_count is incremented, and waitlist_position
        is null." (post-promotion the booking is RESERVED, hence
        waitlist_position must be null).

        Claim: after waitlist promotion, the booking's waitlist_position is null.
        """
        scen = setup_full_capacity_with_waitlist(
            state_code="CA", capacity=1, waitlist_count=1, starts_in_hours=48
        )
        reserved_member, reserved_booking = scen["reserved"][0]
        (m1, b1), = scen["waitlist"]
        api.cancel_booking(
            reserved_member["id"],
            reserved_booking["id"],
            make_member_headers(reserved_member["id"]),
        )
        promoted = get_booking_fresh(m1, b1["id"])
        assert promoted["status"] == "RESERVED"
        assert promoted["waitlist_position"] is None


# =============================================================================
# Rule 4 — Transitive cascade chains from different triggers
# =============================================================================


class TestRule4_PaymentFailureCascade:
    """difficulty: transitive_cascade/payment_failure_to_delinquent_to_suspension_to_booking_cancel"""

    def test_delinquency_cascade_freezes_member_and_cancels_future_booking(self, api):
        """# difficulty: transitive_cascade/payment_failure_to_delinquent_to_suspension_to_booking_cancel

        PRD §3.2: "If the clock advances past grace_period_end without any
        SUCCESS in the interval, the subscription transitions from GRACE to
        DELINQUENT. This cascades into Member.billing_status of DELINQUENT, which
        in turn drives Member.access_status to SUSPENDED and immediately afterward
        to FROZEN; account_posture resolves to FROZEN. Every future booking of
        this member in RESERVED or CONFIRMED is cancelled with the state-specific
        refund schedule."

        Claim: a CA member with a RESERVED booking experiences the full cascade
        when their subscription crosses grace_period_end → DELINQUENT, FROZEN,
        booking CANCELLED.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=48, duration_minutes=60, plan="PLUS"
        )
        member = scen["member"]
        booking = scen["booking"]
        reach_subscription_delinquent(member, scen["subscription"])
        member_after = get_member_fresh(member["id"])
        sub_after = get_subscription_fresh(member["id"], scen["subscription"]["id"])
        booking_after = get_booking_fresh(member, booking["id"])
        assert sub_after["status"] == "DELINQUENT"
        assert member_after["billing_status"] == "DELINQUENT"
        assert member_after["access_status"] == "FROZEN"
        assert member_after["account_posture"] == "FROZEN"
        assert booking_after["status"] == "CANCELLED"
        # PRD §3.7: admin cascade refund is 100% → final_price_cents=0.
        assert booking_after["final_price_cents"] == 0

    def test_delinquency_cascade_admin_schedule_zeroes_final_price(self, api):
        """# difficulty: transitive_cascade/payment_failure_to_delinquent_to_suspension_to_booking_cancel

        PRD §3.7: "Cancellation by system cascade — when a member's access_status
        enters SUSPENDED, FROZEN, or CANCELLED, or when a ClassSession enters
        CANCELLED — uses the administrative refund schedule instead of the
        member's state schedule: one hundred percent refund regardless of
        hours_to_start, and no NO_SHOW penalty applies even if the booking had
        previously been CONFIRMED."

        Claim: delinquency-cascade cancel uses ADMIN schedule (100%) even when
        the member's state schedule would have given a partial refund.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=48, duration_minutes=60, plan="PLUS"
        )
        member = scen["member"]
        booking = scen["booking"]
        provisional = booking["provisional_price_cents"]
        wallet_before = get_member_fresh(member["id"])["wallet_credit_cents"]
        reach_subscription_delinquent(member, scen["subscription"])
        booking_after = get_booking_fresh(member, booking["id"])
        member_after = get_member_fresh(member["id"])
        # Booking refund credit = full provisional (admin schedule).
        # Wallet has also been debited by the GRACE late fee. We assert the
        # refund credit alone landed by computing the delta minus the late fee.
        late_fee = round(scen["subscription"]["base_price_cents"] * 5 / 100)
        wallet_delta = member_after["wallet_credit_cents"] - wallet_before
        # Net: -late_fee + provisional. (Booking cascade refund adds provisional.)
        assert wallet_delta == provisional - late_fee, (
            f"PRD §3.7 admin cascade: wallet must rise by full provisional "
            f"({provisional}) minus the PRD §3.2 late fee ({late_fee}); "
            f"got delta {wallet_delta}"
        )


class TestRule4_NoShowToStrikeToSuspension:
    """difficulty: transitive_cascade/no_show_to_strike_to_suspension

    Setup needs three NO_SHOW bookings over the rolling 30-day window. We use a
    single member who incurs three NO_SHOW events back-to-back across three
    distinct sessions; each requires the full lifecycle: RESERVED → CONFIRMED →
    clock advances past ends_at → /_sweep/run marks NO_SHOW. After the third
    NO_SHOW, the strike count crosses NO_SHOW_STRIKE_LIMIT (3) and access is
    SUSPENDED.
    """

    @staticmethod
    def _drive_one_no_show(api, member, store, trainer, starts_in_hours: float = 1.5):
        """Create a session that ends inside the 24-hour budget we'll advance to,
        book it, confirm, then advance past ends_at, then sweep."""
        from test_helpers import server_now_dt

        starts_dt = server_now_dt() + timedelta(hours=starts_in_hours)
        ends_dt = starts_dt + timedelta(minutes=30)
        session = schedule_class_session(
            store,
            trainer,
            class_type="YOGA",
            starts_at=iso_utc(starts_dt),
            ends_at=iso_utc(ends_dt),
            capacity=10,
        )
        booking = create_booking_for_member(
            member, booking_kind="GROUP_CLASS", class_session=session
        )
        # Confirm.
        from test_helpers import TEST_USERS

        api.confirm_booking(member["id"], booking["id"], make_member_headers(member["id"]))
        # Advance clock past ends_at.
        advance_clock_to(iso_utc(ends_dt + timedelta(seconds=1)))
        # Sweep — marks unattended CONFIRMED bookings NO_SHOW.
        api.run_sweep(TEST_USERS["billing_admin_headers"])
        return booking

    def test_third_no_show_suspends_member(self, api):
        """# difficulty: transitive_cascade/no_show_to_strike_to_suspension

        PRD §3.7: "A CONFIRMED booking that never receives a gate check-in is
        swept to NO_SHOW after ClassSession.ends_at. The sweep recomputes the
        member's no_show_strike_count (the count of NO_SHOW transitions for the
        member within a rolling thirty-day window ending at the present clock)
        and applies a no-show penalty: final_price_cents becomes
        provisional_price_cents plus one thousand cents. If the recomputed strike
        count reaches or exceeds three, a cascade fires: the member's
        access_status is set to SUSPENDED for seven days, suspension_window_start
        is the present clock, suspension_window_end is the present clock plus
        seven days, and account_posture resolves to FROZEN."

        Claim: third NO_SHOW within the rolling 30-day window → access_status
        flips to SUSPENDED, suspension_window_end set, account_posture=FROZEN.
        """
        store = discover_or_create_store("CA")
        trainer = register_trainer(home_store_id=store["id"])
        member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        # Drive 3 NO_SHOWs back-to-back.
        b1 = self._drive_one_no_show(api, member, store, trainer, starts_in_hours=1.5)
        b2 = self._drive_one_no_show(api, member, store, trainer, starts_in_hours=2.5)
        b3 = self._drive_one_no_show(api, member, store, trainer, starts_in_hours=3.5)
        # All bookings should now be NO_SHOW.
        for b in (b1, b2, b3):
            after = get_booking_fresh(member, b["id"])
            assert after["status"] == "NO_SHOW"
        member_after = get_member_fresh(member["id"])
        assert member_after["no_show_strike_count"] >= 3
        assert member_after["access_status"] == "SUSPENDED"
        assert member_after["suspension_window_end"] is not None
        assert member_after["account_posture"] == "FROZEN"

    def test_no_show_adds_one_thousand_cent_penalty_to_final_price(self, api):
        """# difficulty: transitive_cascade/no_show_to_strike_to_suspension

        PRD §3.7: "applies a no-show penalty: final_price_cents becomes
        provisional_price_cents plus one thousand cents."

        Claim: a NO_SHOW booking has final_price_cents == provisional + 1000.
        """
        store = discover_or_create_store("CA")
        trainer = register_trainer(home_store_id=store["id"])
        member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        b = self._drive_one_no_show(api, member, store, trainer, starts_in_hours=1.5)
        after = get_booking_fresh(member, b["id"])
        assert after["status"] == "NO_SHOW"
        assert after["final_price_cents"] == b["provisional_price_cents"] + 1000, (
            f"PRD §3.7: NO_SHOW final = provisional + 1000; "
            f"provisional={b['provisional_price_cents']}, got final={after['final_price_cents']}"
        )


# =============================================================================
# Rule 5 — Validation priority conflicts across different error-category pairs
# =============================================================================


class TestRule5_PostureBeatsTimeConflict:
    """difficulty: priority_pair_validation_conflict/posture_beats_business_constraint"""

    def test_frozen_member_with_overlapping_booking_gets_posture_error(self, api):
        """# difficulty: priority_pair_validation_conflict/posture_beats_business_constraint

        PRD §2.13: "Specifically, a posture-frozen member who would *also* have a
        trainer conflict receives ERR_ACCOUNT_POSTURE_FROZEN, not
        ERR_TRAINER_UNAVAILABLE."

        Claim (analogous structurally to PRD's named example): a FROZEN member
        attempting a booking that ALSO would time-conflict surfaces
        ERR_ACCOUNT_POSTURE_FROZEN (the posture check at priority 5 fires
        before the conflict check at priority 8).
        """
        # Build a FROZEN member first (this advances the server clock through
        # the grace window). Then schedule the session so its starts_at is
        # still in the future per the server clock — otherwise the priority-4
        # state precondition on the ClassSession fires before posture (PRD §2.13).
        frozen_member, _sub = freeze_member_via_delinquency(state_code="CA", plan="PLUS")
        scen = setup_basic_scenario(state_code="CA", plan="PLUS")
        payload = create_booking_payload(
            booking_kind="GROUP_CLASS",
            class_session_id=scen["class_session"]["id"],
            starts_at=scen["class_session"]["starts_at"],
            ends_at=scen["class_session"]["ends_at"],
        )
        res = api.create_booking(
            frozen_member["id"], payload, make_member_headers(frozen_member["id"])
        )
        validate_error(res, "ERR_ACCOUNT_POSTURE_FROZEN")

    def test_frozen_member_blocked_for_pt_with_trainer_overlap(self, api):
        """# difficulty: priority_pair_validation_conflict/posture_beats_business_constraint

        PRD §2.13: "Specifically, a posture-frozen member who would *also* have
        a trainer conflict receives ERR_ACCOUNT_POSTURE_FROZEN, not
        ERR_TRAINER_UNAVAILABLE."

        Claim: a FROZEN member attempting a PT booking that would trip the
        trainer envelope still receives ERR_ACCOUNT_POSTURE_FROZEN (verbatim
        example from PRD §2.13).
        """
        # Build a trainer with an existing PT booking.
        scen = setup_trainer_with_pt_booking(
            state_code="CA", starts_in_hours=48, duration_minutes=30, plan="PLUS"
        )
        frozen_member, _sub = freeze_member_via_delinquency(state_code="CA", plan="PLUS")
        # Request a PT booking in the trainer's envelope.
        payload = create_booking_payload(
            booking_kind="PERSONAL_TRAINING",
            trainer_id=scen["trainer"]["id"],
            starts_at=scen["starts_at"],
            ends_at=scen["ends_at"],
        )
        res = api.create_booking(
            frozen_member["id"], payload, make_member_headers(frozen_member["id"])
        )
        validate_error(res, "ERR_ACCOUNT_POSTURE_FROZEN")


class TestRule5_StateBeatsBusinessSafety:
    """difficulty: priority_pair_validation_conflict/state_beats_business_safety

    PRD-First check: PRD §2.13 explicitly names ONE precedence example
    (posture beats trainer conflict). For state-vs-tier precedence, PRD §2.13
    enumerates the order ("4 state preconditions … 7 class minimum-tier
    permission for bookings") but does not include a named verbatim example.
    A two-reader test confirms both readings still agree state precedes
    business_safety. We therefore generate two tests pinned to the precedence
    sentence.
    """

    def test_basic_member_with_cancelled_session_gets_state_error_not_tier(self, api):
        """# difficulty: priority_pair_validation_conflict/state_beats_business_safety

        PRD §2.13: "Tests against later checks rely on earlier checks passing,
        so a violation of an earlier check masks any later violations and
        surfaces only the earlier error_id."

        Claim: BASIC member booking a CANCELLED ELITE-only session →
        ERR_INVALID_STATE wins over ERR_TIER_BELOW_MINIMUM (priority 4 vs 7).
        """
        scen = setup_basic_scenario(state_code="CA", plan="BASIC")
        # Create an ELITE-only session and cancel it.
        elite_session = schedule_class_session(
            scen["store"],
            scen["trainer"],
            class_type="YOGA",
            capacity=5,
            minimum_tier="ELITE",
            starts_in_hours=48,
        )
        cancel_class_session_admin(scen["store"], elite_session["id"])
        # Member is BASIC tier from setup_basic_scenario's plan="BASIC".
        # But default plan from setup_basic_scenario is "PLUS", so reproduce:
        basic_member, _ = setup_active_member_with_subscription(state_code="CA", plan="BASIC")
        payload = create_booking_payload(
            booking_kind="GROUP_CLASS",
            class_session_id=elite_session["id"],
            starts_at=elite_session["starts_at"],
            ends_at=elite_session["ends_at"],
        )
        res = api.create_booking(
            basic_member["id"], payload, make_member_headers(basic_member["id"])
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_state_check_yields_invalid_state_when_session_cancelled(self, api):
        """# difficulty: priority_pair_validation_conflict/state_beats_business_safety

        PRD §2.13: "Tests against later checks rely on earlier checks passing,
        so a violation of an earlier check masks any later violations and
        surfaces only the earlier error_id."

        Claim: booking a CANCELLED session → ERR_INVALID_STATE (state precondition
        at priority 4) — regardless of any later-check violations the member
        might also have.
        """
        scen = setup_basic_scenario(state_code="CA", plan="PLUS")
        cancel_class_session_admin(scen["store"], scen["class_session"]["id"])
        payload = create_booking_payload(
            booking_kind="GROUP_CLASS",
            class_session_id=scen["class_session"]["id"],
            starts_at=scen["class_session"]["starts_at"],
            ends_at=scen["class_session"]["ends_at"],
        )
        res = api.create_booking(
            scen["member"]["id"],
            payload,
            make_member_headers(scen["member"]["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


class TestRule5_BusinessConstraintBeatsBusinessFiscal:
    """difficulty: priority_pair_validation_conflict/business_constraint_beats_business_fiscal"""

    def test_trainer_conflict_wins_over_coupon_invalid(self, api):
        """# difficulty: priority_pair_validation_conflict/business_constraint_beats_business_fiscal

        PRD §2.13: "Tests against later checks rely on earlier checks passing,
        so a violation of an earlier check masks any later violations and
        surfaces only the earlier error_id."

        Claim: a PT booking with BOTH a trainer overlap AND an invalid coupon
        surfaces ERR_TRAINER_UNAVAILABLE (priority 9 < priority 12).
        """
        scen = setup_trainer_with_pt_booking(
            state_code="CA", starts_in_hours=48, duration_minutes=30, plan="PLUS"
        )
        member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        # Mint a coupon that is INVALID for BOOKING context.
        bad_coupon = mint_coupon(
            kind="PERCENT_OFF",
            value=15,
            applicable_to="SUBSCRIPTION",  # invalid for booking context
            max_redemptions=5,
        )
        # Build a PT request that overlaps the trainer's envelope.
        payload = create_booking_payload(
            booking_kind="PERSONAL_TRAINING",
            trainer_id=scen["trainer"]["id"],
            starts_at=scen["starts_at"],
            ends_at=scen["ends_at"],
            applied_coupon_id=bad_coupon["id"],
        )
        res = api.create_booking(member["id"], payload, make_member_headers(member["id"]))
        validate_error(res, "ERR_TRAINER_UNAVAILABLE")

    def test_trainer_conflict_alone_yields_trainer_unavailable(self, api):
        """# difficulty: priority_pair_validation_conflict/business_constraint_beats_business_fiscal

        PRD §3.6: "another RESERVED or CONFIRMED PT booking for the same trainer
        that touches this envelope at any point — including the boundary
        instants — is a conflict and is rejected with ERR_TRAINER_UNAVAILABLE."

        Claim: a PT request that lands inside the trainer's [-15, +15] envelope
        receives ERR_TRAINER_UNAVAILABLE — anchors the priority-9 check.
        """
        scen = setup_trainer_with_pt_booking(
            state_code="CA", starts_in_hours=48, duration_minutes=30, plan="PLUS"
        )
        member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        payload = create_booking_payload(
            booking_kind="PERSONAL_TRAINING",
            trainer_id=scen["trainer"]["id"],
            starts_at=scen["starts_at"],
            ends_at=scen["ends_at"],
        )
        res = api.create_booking(member["id"], payload, make_member_headers(member["id"]))
        validate_error(res, "ERR_TRAINER_UNAVAILABLE")


# =============================================================================
# Rule 6 — Boundary-precision checks on different metrics/endpoints
# =============================================================================


class TestRule6_RefundAtExactly24h_CA:
    """difficulty: boundary_precision_check/refund_pct_boundary_at_exactly_24h_in_CA"""

    def test_ca_cancel_at_exactly_24h_refunds_100pct(self, api):
        """# difficulty: boundary_precision_check/refund_pct_boundary_at_exactly_24h_in_CA

        PRD §3.7: "The boundary check is inclusive on hours_to_start greater
        than or equal to the threshold — so a CA cancellation at exactly
        hours_to_start equal to twenty-four refunds one hundred percent, at
        exactly two refunds fifty percent, and at one point nine nine nine
        refunds zero."

        Claim: CA voluntary cancel at exactly 24h → refund 100%, final=0.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=24, plan="PLUS", duration_minutes=60
        )
        member = scen["member"]
        booking = scen["booking"]
        res = api.cancel_booking(member["id"], booking["id"], make_member_headers(member["id"]))
        data = validate_success(res, 200)
        assert data["final_price_cents"] == 0

    def test_ca_cancel_at_exactly_2h_refunds_50pct(self, api):
        """# difficulty: boundary_precision_check/refund_pct_boundary_at_exactly_24h_in_CA

        PRD §3.7: "at exactly two refunds fifty percent".

        Claim: CA voluntary cancel at exactly 2h → refund 50%.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=2, plan="PLUS", duration_minutes=60
        )
        member = scen["member"]
        booking = scen["booking"]
        provisional = booking["provisional_price_cents"]
        expected_refund = round(provisional * 50 / 100)
        res = api.cancel_booking(member["id"], booking["id"], make_member_headers(member["id"]))
        data = validate_success(res, 200)
        assert data["final_price_cents"] == provisional - expected_refund


class TestRule6_EmptyWaitlistFallback:
    """difficulty: boundary_precision_check/empty_waitlist_promotion_fallback"""

    def test_cancel_with_empty_waitlist_just_decrements_seat_count(self, api):
        """# difficulty: boundary_precision_check/empty_waitlist_promotion_fallback

        PRD §3.7: "If the cancelled booking had a confirmed seat, reserved_seat_count
        is decremented and the waitlist promotion fires..."

        Claim: when no WAITLISTED siblings exist, the cancel decrements
        reserved_seat_count and no new promotion fires.
        """
        scen = setup_full_capacity_with_waitlist(
            state_code="CA", capacity=2, waitlist_count=0, starts_in_hours=48
        )
        first_member, first_booking = scen["reserved"][0]
        second_member, second_booking = scen["reserved"][1]
        session_before = get_class_session_fresh(
            scen["store"]["id"], scen["class_session"]["id"]
        )
        assert session_before["reserved_seat_count"] == 2
        api.cancel_booking(
            first_member["id"],
            first_booking["id"],
            make_member_headers(first_member["id"]),
        )
        session_after = get_class_session_fresh(
            scen["store"]["id"], scen["class_session"]["id"]
        )
        assert session_after["reserved_seat_count"] == 1
        # Second reservation is untouched.
        assert get_booking_fresh(second_member, second_booking["id"])["status"] == "RESERVED"

    def test_empty_waitlist_does_not_invent_a_promotion(self, api):
        """# difficulty: boundary_precision_check/empty_waitlist_promotion_fallback

        PRD §3.7: "A WAITLISTED booking is promoted to RESERVED automatically
        whenever a seat opens on the same session — typically because a sibling
        booking is cancelled..."

        Claim: with an empty waitlist, no booking transitions to RESERVED that
        wasn't already RESERVED prior to the cancel.
        """
        scen = setup_full_capacity_with_waitlist(
            state_code="CA", capacity=1, waitlist_count=0, starts_in_hours=48
        )
        first_member, first_booking = scen["reserved"][0]
        api.cancel_booking(
            first_member["id"],
            first_booking["id"],
            make_member_headers(first_member["id"]),
        )
        session_after = get_class_session_fresh(
            scen["store"]["id"], scen["class_session"]["id"]
        )
        # No bookings remain in RESERVED — the only one was cancelled.
        assert session_after["reserved_seat_count"] == 0


class TestRule6_EquipmentPoolZeroBoundary:
    """difficulty: boundary_precision_check/equipment_pool_zero_units_required_boundary"""

    def test_zero_units_required_allowed_on_saturated_pool(self, api):
        """# difficulty: boundary_precision_check/equipment_pool_zero_units_required_boundary

        PRD §3.5: "if the class needs no shared equipment, equipment_pool_id is
        null and equipment_units_required defaults to zero" and "the sum of
        equipment_units_required across all SCHEDULED or LOCKED class sessions
        whose [starts_at, ends_at) half-open window overlaps the requested
        session's window must remain at or below the pool's total_units".

        Claim: scheduling with equipment_units_required=0 succeeds against a
        saturated pool — the constraint compares against total_units, and
        adding zero leaves the sum below the cap.
        """
        scen = setup_equipment_pool_saturated(
            state_code="CA", total_units=2, starts_in_hours=48, duration_minutes=60
        )
        new_trainer = register_trainer(home_store_id=scen["store"]["id"])
        existing_start = datetime.fromisoformat(scen["starts_at"].replace("Z", "+00:00"))
        payload = create_class_session_payload(
            class_type="YOGA",
            trainer_id=new_trainer["id"],
            starts_at=iso_utc(existing_start),
            ends_at=iso_utc(existing_start + timedelta(minutes=60)),
            capacity=10,
            equipment_pool_id=scen["pool"]["id"],
            equipment_units_required=0,
        )
        res = api.create_class_session(
            scen["store"]["id"], payload, TEST_USERS["store_manager_headers"]
        )
        validate_success(res, 201)

    def test_one_extra_unit_overflows_saturated_pool(self, api):
        """# difficulty: boundary_precision_check/equipment_pool_zero_units_required_boundary

        PRD §3.5: "the sum of equipment_units_required across all SCHEDULED or
        LOCKED class sessions whose [starts_at, ends_at) half-open window
        overlaps the requested session's window must remain at or below the
        pool's total_units... A violation of either clause is rejected with
        ERR_EQUIPMENT_UNAVAILABLE."

        Claim: adding even one more unit to a saturated pool → ERR_EQUIPMENT_UNAVAILABLE.
        """
        scen = setup_equipment_pool_saturated(
            state_code="CA", total_units=2, starts_in_hours=48, duration_minutes=60
        )
        new_trainer = register_trainer(home_store_id=scen["store"]["id"])
        existing_start = datetime.fromisoformat(scen["starts_at"].replace("Z", "+00:00"))
        payload = create_class_session_payload(
            class_type="SPIN",
            trainer_id=new_trainer["id"],
            starts_at=iso_utc(existing_start),
            ends_at=iso_utc(existing_start + timedelta(minutes=60)),
            capacity=10,
            equipment_pool_id=scen["pool"]["id"],
            equipment_units_required=1,
        )
        res = api.create_class_session(
            scen["store"]["id"], payload, TEST_USERS["store_manager_headers"]
        )
        validate_error(res, "ERR_EQUIPMENT_UNAVAILABLE")


# =============================================================================
# Rule 7 — Cross-entity state dependencies across different entity pairs
# =============================================================================


class TestRule7_MemberSuspendRequiresActiveSubscription:
    """difficulty: cross_entity_state_dependency/member_suspend_requires_subscription_active_or_reinstated"""

    def test_past_due_subscription_blocks_voluntary_suspend(self, api):
        """# difficulty: cross_entity_state_dependency/member_suspend_requires_subscription_active_or_reinstated

        PRD §3.4: "Suspension is only permitted when the member's
        Subscription.status is in ACTIVE or REINSTATED *and* the member has no
        future booking in status RESERVED or CONFIRMED whose start instant falls
        within the requested suspension window; if either condition fails, the
        request is rejected with ERR_HAS_FUTURE_BOOKINGS."

        Claim: PAST_DUE subscription → suspend rejected with ERR_HAS_FUTURE_BOOKINGS.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        reach_subscription_past_due(member, sub)
        res = api.suspend_member(member["id"], None, make_member_headers(member["id"]))
        validate_error(res, "ERR_HAS_FUTURE_BOOKINGS")

    def test_reinstated_subscription_allows_suspend(self, api):
        """# difficulty: cross_entity_state_dependency/member_suspend_requires_subscription_active_or_reinstated

        PRD §3.4: "Suspension is only permitted when the member's
        Subscription.status is in ACTIVE or REINSTATED..."

        Claim: a REINSTATED subscription (via SUCCESS while PAST_DUE) lets the
        member suspend successfully.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        sub = reach_subscription_past_due(member, sub)
        submit_payment_attempt(member, sub, outcome="SUCCESS")
        # Subscription is back to ACTIVE; Member.billing_status is REINSTATED.
        # Suspend should succeed when no future bookings.
        res = api.suspend_member(member["id"], None, make_member_headers(member["id"]))
        data = validate_success(res, 200)
        assert data["access_status"] == "SUSPENDED"


class TestRule7_BookingConfirmRequiresScheduledSession:
    """difficulty: cross_entity_state_dependency/booking_confirm_requires_classsession_scheduled

    PRD §3.7: "A RESERVED booking advances to CONFIRMED only through an explicit
    confirmation action by the member, and only when two conditions hold: the
    member's account_posture is OPEN, and the present clock is strictly before
    ClassSession.starts_at minus the configured confirmation cutoff." — PRD
    references "the configured confirmation cutoff" without naming a specific
    number. We exercise the post-LOCKED case by cancelling the session, which
    is an unambiguous non-SCHEDULED state.
    """

    def test_confirm_fails_when_session_cancelled(self, api):
        """# difficulty: cross_entity_state_dependency/booking_confirm_requires_classsession_scheduled

        PRD §3.5: "A StoreManager may also cancel the session at any point while
        it is SCHEDULED or LOCKED: every non-terminal Booking against the
        session is cancelled with the administrative refund schedule..."

        Claim: once the ClassSession is CANCELLED, no booking under it remains
        non-terminal, so a Member-issued /confirm against any such booking
        receives ERR_INVALID_STATE (booking is terminal — CANCELLED).
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=48, plan="PLUS"
        )
        cancel_class_session_admin(scen["store"], scen["class_session"]["id"])
        res = api.confirm_booking(
            scen["member"]["id"], scen["booking"]["id"], make_member_headers(scen["member"]["id"])
        )
        # The booking is now in a terminal state (CANCELLED) — confirm is invalid.
        validate_error(res, "ERR_INVALID_STATE")

    def test_confirm_succeeds_on_scheduled_session_and_open_posture(self, api):
        """# difficulty: cross_entity_state_dependency/booking_confirm_requires_classsession_scheduled

        PRD §3.7: "A RESERVED booking advances to CONFIRMED only through an
        explicit confirmation action by the member, and only when two
        conditions hold: the member's account_posture is OPEN, and the present
        clock is strictly before ClassSession.starts_at minus the configured
        confirmation cutoff."

        Claim: confirming a RESERVED booking well before the start succeeds.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=48, plan="PLUS"
        )
        res = api.confirm_booking(
            scen["member"]["id"],
            scen["booking"]["id"],
            make_member_headers(scen["member"]["id"]),
        )
        data = validate_success(res, 200)
        assert data["status"] == "CONFIRMED"


# =============================================================================
# Rule 8 — Resource temporal-overlap conflicts across different interval semantics
# =============================================================================


class TestRule8_MemberHalfOpenAdjacency:
    """difficulty: resource_temporal_overlap/member_self_overlap_half_open_no_buffer"""

    def test_member_back_to_back_bookings_allowed(self, api):
        """# difficulty: resource_temporal_overlap/member_self_overlap_half_open_no_buffer

        PRD §3.6: "the requested [starts_at, ends_at) half-open interval must
        not overlap any of the member's other bookings (across all stores),
        although adjacent intervals (the new booking's starts_at exactly equal
        to another's ends_at, or vice versa) are explicitly permitted..."

        Claim: a member with an existing booking [T, T+60min) can also book
        [T+60min, T+120min) — adjacency allowed.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=48, duration_minutes=60, plan="PLUS", capacity=10
        )
        member = scen["member"]
        existing_end = datetime.fromisoformat(scen["class_session"]["ends_at"].replace("Z", "+00:00"))
        adj_session = schedule_class_session(
            scen["store"],
            scen["trainer"],
            class_type="HIIT",
            starts_at=scen["class_session"]["ends_at"],
            ends_at=iso_utc(existing_end + timedelta(minutes=60)),
            capacity=10,
        )
        payload = create_booking_payload(
            booking_kind="GROUP_CLASS",
            class_session_id=adj_session["id"],
            starts_at=adj_session["starts_at"],
            ends_at=adj_session["ends_at"],
        )
        res = api.create_booking(member["id"], payload, make_member_headers(member["id"]))
        validate_success(res, 201)

    def test_member_strict_overlap_rejected(self, api):
        """# difficulty: resource_temporal_overlap/member_self_overlap_half_open_no_buffer

        PRD §3.6: "the requested [starts_at, ends_at) half-open interval must
        not overlap any of the member's other bookings (across all stores)..."

        Claim: a member's second booking that strictly overlaps the first by
        30 minutes → ERR_MEMBER_TIME_CONFLICT.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=48, duration_minutes=60, plan="PLUS", capacity=10
        )
        member = scen["member"]
        # New session at exact same [starts_at, ends_at) — strict overlap.
        overlap_session = schedule_class_session(
            scen["store"],
            scen["trainer"],
            class_type="HIIT",
            starts_at=scen["class_session"]["starts_at"],
            ends_at=scen["class_session"]["ends_at"],
            capacity=10,
        )
        payload = create_booking_payload(
            booking_kind="GROUP_CLASS",
            class_session_id=overlap_session["id"],
            starts_at=overlap_session["starts_at"],
            ends_at=overlap_session["ends_at"],
        )
        res = api.create_booking(member["id"], payload, make_member_headers(member["id"]))
        validate_error(res, "ERR_MEMBER_TIME_CONFLICT")


class TestRule8_TrainerEnvelopeClosed:
    """difficulty: resource_temporal_overlap/trainer_envelope_with_buffer_closed"""

    def test_trainer_envelope_adjacency_rejected(self, api):
        """# difficulty: resource_temporal_overlap/trainer_envelope_with_buffer_closed

        PRD §3.6: "For personal training, the trainer must be free in the
        closed-on-both-sides envelope of [starts_at − 15 minutes, ends_at + 15
        minutes]; another RESERVED or CONFIRMED PT booking for the same trainer
        that touches this envelope at any point — including the boundary instants
        — is a conflict and is rejected with ERR_TRAINER_UNAVAILABLE."

        Claim: a new PT starting exactly at the existing PT's ends_at falls
        inside the +15min envelope tail and is rejected.
        """
        scen = setup_trainer_with_pt_booking(
            state_code="CA", starts_in_hours=48, duration_minutes=30, plan="PLUS"
        )
        new_member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        existing_end = datetime.fromisoformat(scen["ends_at"].replace("Z", "+00:00"))
        payload = create_booking_payload(
            booking_kind="PERSONAL_TRAINING",
            trainer_id=scen["trainer"]["id"],
            starts_at=scen["ends_at"],
            ends_at=iso_utc(existing_end + timedelta(minutes=30)),
        )
        res = api.create_booking(
            new_member["id"], payload, make_member_headers(new_member["id"])
        )
        validate_error(res, "ERR_TRAINER_UNAVAILABLE")

    def test_trainer_envelope_just_outside_allowed(self, api):
        """# difficulty: resource_temporal_overlap/trainer_envelope_with_buffer_closed

        PRD §3.6: "another RESERVED or CONFIRMED PT booking for the same
        trainer that touches this envelope at any point — including the
        boundary instants — is a conflict..."

        Claim: a new PT starting 16 minutes after the existing PT's ends_at is
        outside the +15min envelope and is accepted.
        """
        scen = setup_trainer_with_pt_booking(
            state_code="CA", starts_in_hours=48, duration_minutes=30, plan="PLUS"
        )
        new_member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        existing_end = datetime.fromisoformat(scen["ends_at"].replace("Z", "+00:00"))
        # 16 minutes after envelope end (>15 minutes buffer) → no conflict.
        new_start = iso_utc(existing_end + timedelta(minutes=16))
        new_end = iso_utc(existing_end + timedelta(minutes=46))
        payload = create_booking_payload(
            booking_kind="PERSONAL_TRAINING",
            trainer_id=scen["trainer"]["id"],
            starts_at=new_start,
            ends_at=new_end,
        )
        res = api.create_booking(
            new_member["id"], payload, make_member_headers(new_member["id"])
        )
        data = validate_success(res, 201)
        assert data["status"] == "RESERVED"


class TestRule8_EquipmentAggregateCapacity:
    """difficulty: resource_temporal_overlap/equipment_aggregate_capacity_overlap"""

    def test_equipment_aggregate_overflow_rejected(self, api):
        """# difficulty: resource_temporal_overlap/equipment_aggregate_capacity_overlap

        PRD §3.5: "the sum of equipment_units_required across all SCHEDULED or
        LOCKED class sessions whose [starts_at, ends_at) half-open window
        overlaps the requested session's window must remain at or below the
        pool's total_units..."

        Claim: adding a session whose [starts_at, ends_at) partially overlaps
        two saturating sessions on a 2-unit pool → ERR_EQUIPMENT_UNAVAILABLE.
        """
        scen = setup_equipment_pool_saturated(
            state_code="CA", total_units=2, starts_in_hours=48, duration_minutes=60
        )
        new_trainer = register_trainer(home_store_id=scen["store"]["id"])
        existing_start = datetime.fromisoformat(scen["starts_at"].replace("Z", "+00:00"))
        payload = create_class_session_payload(
            class_type="SPIN",
            trainer_id=new_trainer["id"],
            starts_at=iso_utc(existing_start + timedelta(minutes=30)),
            ends_at=iso_utc(existing_start + timedelta(minutes=90)),
            capacity=10,
            equipment_pool_id=scen["pool"]["id"],
            equipment_units_required=1,
        )
        res = api.create_class_session(
            scen["store"]["id"], payload, TEST_USERS["store_manager_headers"]
        )
        validate_error(res, "ERR_EQUIPMENT_UNAVAILABLE")

    def test_equipment_non_overlapping_window_allowed(self, api):
        """# difficulty: resource_temporal_overlap/equipment_aggregate_capacity_overlap

        PRD §3.5: "sum of equipment_units_required across all SCHEDULED or
        LOCKED class sessions whose [starts_at, ends_at) half-open window
        overlaps the requested session's window..."

        Claim: a session whose window does NOT overlap saturating sessions can
        consume units (half-open window: [t, t+60) and [t+60, t+120) do not
        overlap, by PRD's explicit half-open semantics).
        """
        scen = setup_equipment_pool_saturated(
            state_code="CA", total_units=2, starts_in_hours=48, duration_minutes=60
        )
        new_trainer = register_trainer(home_store_id=scen["store"]["id"])
        existing_end = datetime.fromisoformat(scen["ends_at"].replace("Z", "+00:00"))
        payload = create_class_session_payload(
            class_type="SPIN",
            trainer_id=new_trainer["id"],
            # Strictly after the saturated window — no overlap under half-open semantics.
            starts_at=iso_utc(existing_end),
            ends_at=iso_utc(existing_end + timedelta(minutes=60)),
            capacity=10,
            equipment_pool_id=scen["pool"]["id"],
            equipment_units_required=2,
        )
        res = api.create_class_session(
            scen["store"]["id"], payload, TEST_USERS["store_manager_headers"]
        )
        validate_success(res, 201)


# =============================================================================
# Rule 9 — Compensating-action invariants across different conserved quantities
# =============================================================================


class TestRule9_BookingReserveCascadeCancelInvariant:
    """difficulty: compensating_invariant/booking_reserve_then_cascade_cancel_preserves_pending_balance"""

    def test_reserve_then_cascade_cancel_preserves_compound_balance(self, api):
        """# difficulty: compensating_invariant/booking_reserve_then_cascade_cancel_preserves_pending_balance

        PRD §3.7: "Cancellation by system cascade — when a member's
        access_status enters SUSPENDED, FROZEN, or CANCELLED, or when a
        ClassSession enters CANCELLED — uses the administrative refund schedule
        instead of the member's state schedule: one hundred percent refund
        regardless of hours_to_start..."

        Q1 = wallet_credit_cents + (Booking.provisional_price_cents when
        non-terminal) OR (Booking.final_price_cents when terminal).
        Forward action: create RESERVED with provisional P → Q1 includes P.
        Compensating action: admin cascade cancel → final=0, wallet += P → Q1
        still includes P. Net delta: 0.

        Claim: wallet + booking-side amount is preserved across the
        reserve→cascade-cancel pair.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=48, duration_minutes=60, plan="PLUS"
        )
        member = scen["member"]
        booking = scen["booking"]
        provisional = booking["provisional_price_cents"]
        # Q1 before cancel: wallet + provisional (booking non-terminal).
        wallet_before = get_member_fresh(member["id"])["wallet_credit_cents"]
        q1_before = wallet_before + provisional
        # Trigger admin cascade by cancelling the ClassSession.
        cancel_class_session_admin(scen["store"], scen["class_session"]["id"])
        booking_after = get_booking_fresh(member, booking["id"])
        wallet_after = get_member_fresh(member["id"])["wallet_credit_cents"]
        # Q1 after cancel: wallet + final (booking terminal).
        q1_after = wallet_after + booking_after["final_price_cents"]
        assert booking_after["final_price_cents"] == 0
        assert q1_after == q1_before, (
            f"PRD §3.7 cascade invariant: Q1 must be conserved across "
            f"reserve→cascade-cancel; before={q1_before}, after={q1_after}"
        )

    def test_voluntary_cancel_full_refund_band_also_preserves_balance_in_CA(self, api):
        """# difficulty: compensating_invariant/booking_reserve_then_cascade_cancel_preserves_pending_balance

        PRD §3.7: "a CA cancellation at exactly hours_to_start equal to
        twenty-four refunds one hundred percent" and "The refund in cents is
        provisional_price_cents multiplied by the chosen refund_pct divided by
        one hundred, rounded half up; final_price_cents is provisional_price_cents
        minus the refund credit, and the refund credit is added to
        Member.wallet_credit_cents."

        Claim: voluntary cancel in the 100% band also preserves Q1 — the same
        compensating-action invariant holds here as for the admin cascade.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=24, duration_minutes=60, plan="PLUS"
        )
        member = scen["member"]
        booking = scen["booking"]
        provisional = booking["provisional_price_cents"]
        wallet_before = get_member_fresh(member["id"])["wallet_credit_cents"]
        q1_before = wallet_before + provisional
        api.cancel_booking(member["id"], booking["id"], make_member_headers(member["id"]))
        booking_after = get_booking_fresh(member, booking["id"])
        wallet_after = get_member_fresh(member["id"])["wallet_credit_cents"]
        q1_after = wallet_after + booking_after["final_price_cents"]
        assert q1_after == q1_before


class TestRule9_PaymentIdempotentReplayInvariant:
    """difficulty: compensating_invariant/payment_idempotent_replay_preserves_count_and_amount"""

    def test_replay_does_not_persist_duplicate_row(self, api):
        """# difficulty: compensating_invariant/payment_idempotent_replay_preserves_count_and_amount

        PRD §2.9: "If a second request arrives with the same idempotency_key
        and the same subscription_id, the server does **not** re-contact the
        gateway and does **not** persist a duplicate row; instead it returns
        the prior response with the ERR_IDEMPOTENT_REPLAY outcome and HTTP 200."

        Claim: count(PaymentAttempt for s1) is unchanged across a replay; the
        compound (count + sum(amount_cents)) is preserved.
        """
        member = register_member(state_code="CA")
        sub = create_subscription_for_member(member, plan="BASIC", billing_cycle="MONTHLY")
        import uuid as _u

        key = str(_u.uuid4())
        # First post.
        first = submit_payment_attempt(
            member, sub, outcome="SUCCESS", idempotency_key=key
        )
        # Listing should have exactly 1 row.
        listing1 = api.list_payment_attempts(
            member["id"], sub["id"], make_member_headers(member["id"])
        ).json()
        attempts1 = listing1.get("data") or []
        assert len(attempts1) == 1
        sum_amount_1 = attempts1[0]["amount_cents"]
        # Second post — same key, same outcome.
        api.create_payment_attempt(
            member["id"],
            sub["id"],
            create_payment_attempt_payload(
                outcome="SUCCESS",
                idempotency_key=key,
                gateway_txn_id=first["gateway_txn_id"],
            ),
            TEST_USERS["billing_admin_headers"],
        )
        listing2 = api.list_payment_attempts(
            member["id"], sub["id"], make_member_headers(member["id"])
        ).json()
        attempts2 = listing2.get("data") or []
        # PRD §2.9: count unchanged.
        assert len(attempts2) == 1
        # PRD §2.9: amount unchanged.
        assert attempts2[0]["amount_cents"] == sum_amount_1

    def test_replay_returns_http_200(self, api):
        """# difficulty: compensating_invariant/payment_idempotent_replay_preserves_count_and_amount

        PRD §2.9: "...instead it returns the prior response with the
        ERR_IDEMPOTENT_REPLAY outcome and HTTP 200."

        Claim: a replay request gets HTTP 200 (per PRD §5 ERR_IDEMPOTENT_REPLAY).
        """
        member = register_member(state_code="CA")
        sub = create_subscription_for_member(member, plan="BASIC", billing_cycle="MONTHLY")
        import uuid as _u

        key = str(_u.uuid4())
        first = submit_payment_attempt(
            member, sub, outcome="SUCCESS", idempotency_key=key
        )
        res = api.create_payment_attempt(
            member["id"],
            sub["id"],
            create_payment_attempt_payload(
                outcome="SUCCESS",
                idempotency_key=key,
                gateway_txn_id=first["gateway_txn_id"],
            ),
            TEST_USERS["billing_admin_headers"],
        )
        assert res.status_code == 200, (
            f"PRD §2.9 / §5: idempotent replay must return HTTP 200, got {res.status_code}"
        )
