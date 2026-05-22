"""Voluntary suspension, resume, cancellation (PRD §3.4)."""

import pytest

from test_helpers import (
    TEST_USERS,
    assert_account_posture_invariant,
    create_booking_for_member,
    get_member_fresh,
    get_subscription_fresh,
    make_member_headers,
    reach_subscription_past_due,
    setup_active_member_with_subscription,
    setup_member_with_existing_booking,
    submit_payment_attempt,
    suspend_member_voluntarily,
    validate_error,
    validate_success,
)


class TestVoluntarySuspend:

    def test_suspend_active_subscription_sets_window_and_frozen_posture(self, api):
        """PRD §3.4: "On success, suspension_window_start is set to the current
        clock, suspension_window_end is set to the present clock plus the maximum
        number of suspension days the member's state_code permits (or the smaller
        of that per-state cap and requested_days when requested_days is provided),
        access_status flips to SUSPENDED, and account_posture resolves to FROZEN."

        Claim: voluntary suspend on an ACTIVE-subscription member without future
        bookings → access_status=SUSPENDED, account_posture=FROZEN, windows set.
        """
        member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        res = api.suspend_member(member["id"], None, make_member_headers(member["id"]))
        data = validate_success(res, 200)
        assert data["access_status"] == "SUSPENDED"
        assert data["account_posture"] == "FROZEN"
        assert data["suspension_window_start"] is not None
        assert data["suspension_window_end"] is not None
        assert_account_posture_invariant(data)

    def test_suspend_rejected_when_subscription_not_active_or_reinstated(self, api):
        """PRD §3.4: "Suspension is only permitted when the member's
        Subscription.status is in ACTIVE or REINSTATED *and* the member has no
        future booking in status RESERVED or CONFIRMED whose start instant falls
        within the requested suspension window; if either condition fails, the
        request is rejected with ERR_HAS_FUTURE_BOOKINGS."

        Claim: a PAST_DUE subscription → suspend rejected with ERR_HAS_FUTURE_BOOKINGS.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        sub = reach_subscription_past_due(member, sub)
        assert sub["status"] == "PAST_DUE"
        res = api.suspend_member(member["id"], None, make_member_headers(member["id"]))
        validate_error(res, "ERR_HAS_FUTURE_BOOKINGS")

    def test_suspend_rejected_with_future_reserved_booking(self, api):
        """PRD §3.4: "Suspension is only permitted when the member's
        Subscription.status is in ACTIVE or REINSTATED *and* the member has no
        future booking in status RESERVED or CONFIRMED whose start instant falls
        within the requested suspension window; if either condition fails, the
        request is rejected with ERR_HAS_FUTURE_BOOKINGS."

        Claim: an ACTIVE-subscription member with a future RESERVED booking →
        suspend rejected with ERR_HAS_FUTURE_BOOKINGS.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=48, plan="PLUS"
        )
        member = scen["member"]
        res = api.suspend_member(member["id"], None, make_member_headers(member["id"]))
        validate_error(res, "ERR_HAS_FUTURE_BOOKINGS")


class TestResume:

    def test_resume_from_suspended(self, api):
        """PRD §3.4: "A member may also resume early through the resume endpoint,
        which is permitted whenever access_status is SUSPENDED; the suspension
        window is cleared and access_status flips back to ACTIVE."

        Claim: resume from SUSPENDED → access_status=ACTIVE; suspension window
        cleared (both null).
        """
        member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        suspended = suspend_member_voluntarily(member)
        assert suspended["access_status"] == "SUSPENDED"
        res = api.resume_member(member["id"], make_member_headers(member["id"]))
        data = validate_success(res, 200)
        assert data["access_status"] == "ACTIVE"
        assert data["suspension_window_start"] is None
        assert data["suspension_window_end"] is None
        assert_account_posture_invariant(data)


class TestCancellation:

    def test_cancel_sets_cancellation_effective_at_to_period_end_and_disables_renew(self, api):
        """PRD §3.4: "On success, Subscription.cancellation_effective_at is set to
        the subscription's current_period_end (so cancellation is voluntary and
        end-of-period, not immediate), Subscription.auto_renew is forced to false,
        and Member.account_posture becomes FROZEN."

        Claim: voluntary cancel → cancellation_effective_at == current_period_end,
        auto_renew=false, posture=FROZEN.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        period_end = sub["current_period_end"]
        res = api.cancel_member(member["id"], make_member_headers(member["id"]))
        validate_success(res, 200)
        member_after = get_member_fresh(member["id"])
        sub_after = get_subscription_fresh(member["id"], sub["id"])
        assert sub_after["cancellation_effective_at"] == period_end, (
            f"PRD §3.4: cancellation_effective_at must equal current_period_end, "
            f"got {sub_after['cancellation_effective_at']} vs {period_end}"
        )
        assert sub_after["auto_renew"] is False
        assert member_after["account_posture"] == "FROZEN"
        assert_account_posture_invariant(member_after)
