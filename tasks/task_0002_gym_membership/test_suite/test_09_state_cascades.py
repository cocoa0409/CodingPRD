"""Cross-axis cascades and posture derivation (PRD §2.6, §2.8, §3.2, §3.7)."""

import pytest

from test_helpers import (
    advance_clock_to,
    assert_account_posture_invariant,
    create_booking_for_member,
    freeze_member_via_delinquency,
    get_booking_fresh,
    get_member_fresh,
    hours_from_now_iso,
    make_member_headers,
    reach_subscription_delinquent,
    schedule_class_session,
    setup_active_member_with_subscription,
    setup_basic_scenario,
    setup_member_with_existing_booking,
    submit_payment_attempt,
    suspend_member_voluntarily,
)


class TestPostureDerivation:

    def test_active_open_after_activation(self, api):
        """PRD §2.6: "If access_status is in SUSPENDED, FROZEN, or CANCELLED, the
        posture is FROZEN regardless of billing. Otherwise, if billing_status is in
        PAST_DUE, GRACE, or DELINQUENT, the posture is RESTRICTED. Otherwise — that
        is, when billing_status is in CURRENT or REINSTATED and access_status is
        ACTIVE — the posture is OPEN."

        Claim: CURRENT+ACTIVE → OPEN posture.
        """
        member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        assert member["billing_status"] == "CURRENT"
        assert member["access_status"] == "ACTIVE"
        assert member["account_posture"] == "OPEN"
        assert_account_posture_invariant(member)

    def test_past_due_restricted_when_access_active(self, api):
        """PRD §2.6: "If access_status is in SUSPENDED, FROZEN, or CANCELLED, the
        posture is FROZEN regardless of billing. Otherwise, if billing_status is in
        PAST_DUE, GRACE, or DELINQUENT, the posture is RESTRICTED."

        Claim: PAST_DUE billing + ACTIVE access → RESTRICTED posture.
        """
        from test_helpers import reach_subscription_past_due

        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        reach_subscription_past_due(member, sub)
        member = get_member_fresh(member["id"])
        assert member["billing_status"] == "PAST_DUE"
        assert member["access_status"] == "ACTIVE"
        assert member["account_posture"] == "RESTRICTED"

    def test_suspended_overrides_billing_to_frozen(self, api):
        """PRD §2.6: "If access_status is in SUSPENDED, FROZEN, or CANCELLED, the
        posture is FROZEN regardless of billing."

        Claim: CURRENT+SUSPENDED → FROZEN posture (access dimension dominates).
        """
        member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        suspended = suspend_member_voluntarily(member)
        assert suspended["access_status"] == "SUSPENDED"
        assert suspended["account_posture"] == "FROZEN"
        assert_account_posture_invariant(suspended)


class TestDelinquencyCascade:

    def test_delinquency_cancels_future_reserved_bookings(self, api):
        """PRD §3.2: "Every future booking of this member in RESERVED or CONFIRMED
        is cancelled with the state-specific refund schedule." and PRD §3.7's
        admin/cascade rule overrides it to 100% refund.

        PRD §3.7: "Cancellation by system cascade — when a member's access_status
        enters SUSPENDED, FROZEN, or CANCELLED, or when a ClassSession enters
        CANCELLED — uses the administrative refund schedule instead of the
        member's state schedule: one hundred percent refund regardless of
        hours_to_start..."

        Claim: a member with a future RESERVED booking who becomes DELINQUENT has
        that booking CANCELLED with final_price_cents=0 (admin cascade refund).
        """
        # Build a member + future RESERVED booking, then drive sub to DELINQUENT.
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=48, duration_minutes=60, plan="PLUS"
        )
        member = scen["member"]
        booking = scen["booking"]
        subscription = scen["subscription"]
        provisional = booking["provisional_price_cents"]
        wallet_before = get_member_fresh(member["id"])["wallet_credit_cents"]
        # Walk the subscription to DELINQUENT (via PAST_DUE → GRACE → clock-cross).
        reach_subscription_delinquent(member, subscription)
        # Booking is cancelled with 100% admin refund.
        booking_after = get_booking_fresh(member, booking["id"])
        assert booking_after["status"] == "CANCELLED"
        assert booking_after["final_price_cents"] == 0, (
            f"PRD §3.7 admin cascade: 100% refund (final=0), got {booking_after['final_price_cents']}"
        )
        member_after = get_member_fresh(member["id"])
        # Wallet receives the refund credit (offset by any late-payment penalty from earlier).
        # Net delta: +provisional from booking refund, -penalty from GRACE step.
        # We assert the booking's refund credit landed in the wallet without prescribing
        # the precise overall wallet number (that's tested separately in test_03).
        assert (
            member_after["wallet_credit_cents"] - wallet_before
        ) >= provisional - sub_late_fee_cents(subscription, member), (
            "Wallet must include the booking's full provisional as refund credit "
            "(PRD §3.7 admin schedule)."
        )
        # Member access is FROZEN per the cascade.
        assert member_after["access_status"] == "FROZEN"
        assert member_after["account_posture"] == "FROZEN"


def sub_late_fee_cents(subscription, member) -> int:
    """Helper for cascade-wallet math: PRD §3.2 late fee = state% * base_price_cents."""
    pct_by_state = {"CA": 5, "NY": 8, "TX": 3}
    return round(subscription["base_price_cents"] * pct_by_state[member["state_code"]] / 100)
