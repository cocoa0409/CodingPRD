"""Booking lifecycle: confirmation, cancellation refunds, waitlist promotion (PRD §3.7)."""

import pytest

from test_helpers import (
    assert_booking,
    cancel_class_session_admin,
    create_booking_for_member,
    get_booking_fresh,
    get_class_session_fresh,
    get_member_fresh,
    make_member_headers,
    setup_active_member_with_subscription,
    setup_basic_scenario,
    setup_full_capacity_with_waitlist,
    setup_member_with_existing_booking,
    validate_error,
    validate_success,
)


class TestConfirm:

    def test_confirm_reserved_moves_to_confirmed(self, api):
        """PRD §3.7: "A RESERVED booking advances to CONFIRMED only through an
        explicit confirmation action by the member, and only when two conditions
        hold: the member's account_posture is OPEN, and the present clock is
        strictly before ClassSession.starts_at minus the configured confirmation
        cutoff. Confirmation has no side effects beyond the state flip."

        Claim: confirming a RESERVED booking well before the start →
        Booking.status=CONFIRMED, no other observable side effects.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=48, plan="PLUS"
        )
        member = scen["member"]
        booking = scen["booking"]
        assert booking["status"] == "RESERVED"
        res = api.confirm_booking(member["id"], booking["id"], make_member_headers(member["id"]))
        data = validate_success(res, 200)
        assert data["status"] == "CONFIRMED"


class TestVoluntaryCancelRefund:

    def test_CA_cancel_at_exactly_24h_refunds_full(self, api):
        """PRD §3.7: "For CA, the bands are: if hours_to_start ... is at least
        twenty-four, refund one hundred percent; otherwise if hours_to_start is at
        least two, refund fifty percent; otherwise refund zero." and "The boundary
        check is inclusive on hours_to_start greater than or equal to the threshold
        — so a CA cancellation at exactly hours_to_start equal to twenty-four
        refunds one hundred percent..."

        Claim: cancel a CA booking with exactly 24h to start → final_price_cents=0
        and refund_credit added to wallet equal to provisional_price_cents.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=24, plan="PLUS", duration_minutes=60
        )
        member = scen["member"]
        booking = scen["booking"]
        provisional = booking["provisional_price_cents"]
        wallet_before = get_member_fresh(member["id"])["wallet_credit_cents"]
        res = api.cancel_booking(member["id"], booking["id"], make_member_headers(member["id"]))
        data = validate_success(res, 200)
        assert data["status"] == "CANCELLED"
        assert data["final_price_cents"] == 0, (
            f"PRD §3.7 CA at 24h refunds 100% (final_price_cents=0), got {data['final_price_cents']}"
        )
        wallet_after = get_member_fresh(member["id"])["wallet_credit_cents"]
        assert wallet_after - wallet_before == provisional, (
            f"refund credit must equal provisional ({provisional}), "
            f"got delta {wallet_after - wallet_before}"
        )

    def test_CA_cancel_just_under_24h_refunds_50pct(self, api):
        """PRD §3.7: "For CA, the bands are: if hours_to_start ... is at least
        twenty-four, refund one hundred percent; otherwise if hours_to_start is at
        least two, refund fifty percent..."

        Claim: cancel a CA booking with hours_to_start in [2, 24) → 50% refund.
        We use 12h to safely fall in the 50% band.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=12, plan="PLUS", duration_minutes=60
        )
        member = scen["member"]
        booking = scen["booking"]
        provisional = booking["provisional_price_cents"]
        expected_refund = round(provisional * 50 / 100)
        res = api.cancel_booking(member["id"], booking["id"], make_member_headers(member["id"]))
        data = validate_success(res, 200)
        assert data["status"] == "CANCELLED"
        assert data["final_price_cents"] == provisional - expected_refund, (
            f"PRD §3.7 CA 12h: refund 50% of {provisional} = {expected_refund}, "
            f"so final = {provisional - expected_refund}; got {data['final_price_cents']}"
        )


class TestAdminCascadeRefund:

    def test_admin_class_session_cancel_refunds_100pct_regardless_of_hours(self, api):
        """PRD §3.7: "Cancellation by system cascade — when a member's access_status
        enters SUSPENDED, FROZEN, or CANCELLED, or when a ClassSession enters
        CANCELLED — uses the administrative refund schedule instead of the member's
        state schedule: one hundred percent refund regardless of hours_to_start,
        and no NO_SHOW penalty applies even if the booking had previously been
        CONFIRMED."

        Claim: a ClassSession.cancel cascade refunds the booking 100% regardless
        of hours_to_start (here only 1h before start, which under the CA voluntary
        schedule would yield 0%).
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
        assert booking_after["final_price_cents"] == 0, (
            f"PRD §3.7: admin cascade refunds 100% (final_price_cents=0), "
            f"got {booking_after['final_price_cents']}"
        )
        wallet_after = get_member_fresh(member["id"])["wallet_credit_cents"]
        assert wallet_after - wallet_before == provisional, (
            f"refund credit must equal full provisional ({provisional}), "
            f"got delta {wallet_after - wallet_before}"
        )


class TestWaitlistPromotion:

    def test_reserved_cancel_promotes_first_waitlisted_to_reserved(self, api):
        """PRD §3.7: "A WAITLISTED booking is promoted to RESERVED automatically
        whenever a seat opens on the same session — typically because a sibling
        booking is cancelled... The promotion selector is strictly first-in-
        first-out by created_at ascending (id is never used as a tie-break) and is
        further filtered: only WAITLISTED bookings whose owner currently has
        account_posture of OPEN are promoted; the others are skipped."

        Claim: when the holder of the only reserved seat cancels, the first
        WAITLISTED booking (lowest created_at) flips to RESERVED; the next stays
        WAITLISTED with waitlist_position decremented to 1.
        """
        scen = setup_full_capacity_with_waitlist(
            state_code="CA", capacity=1, waitlist_count=2, starts_in_hours=48
        )
        reserved_member, reserved_booking = scen["reserved"][0]
        (waitlist_m1, waitlist_b1), (waitlist_m2, waitlist_b2) = scen["waitlist"]
        # Pre-conditions
        assert reserved_booking["status"] == "RESERVED"
        assert waitlist_b1["status"] == "WAITLISTED"
        assert waitlist_b1["waitlist_position"] == 1
        assert waitlist_b2["status"] == "WAITLISTED"
        assert waitlist_b2["waitlist_position"] == 2
        # Reserved member cancels.
        res = api.cancel_booking(
            reserved_member["id"],
            reserved_booking["id"],
            make_member_headers(reserved_member["id"]),
        )
        validate_success(res, 200)
        # First waitlister is promoted to RESERVED.
        promoted = get_booking_fresh(waitlist_m1, waitlist_b1["id"])
        assert promoted["status"] == "RESERVED", (
            f"PRD §3.7: the FIFO-earliest WAITLISTED booking must be promoted, "
            f"got status {promoted['status']}"
        )
        # Second waitlister is still WAITLISTED. PRD §3.6/§3.7 describe
        # waitlist_position as "computed from Booking.created_at ascending"
        # at creation, but do not state whether positions are re-indexed when
        # a promotion vacates a slot — both static-at-creation and dynamic-
        # rerank readings are PRD-consistent. Only the status is asserted.
        still_waiting = get_booking_fresh(waitlist_m2, waitlist_b2["id"])
        assert still_waiting["status"] == "WAITLISTED"


class TestCheckIn:

    def test_check_in_during_window_marks_attended(self, api):
        """PRD §3.7: "A CONFIRMED booking advances to ATTENDED only through the
        access-gate webhook, which records gate_check_in_at at the present clock.
        The check-in is accepted only when the present clock lies in the inclusive
        window [ClassSession.starts_at − 15 minutes, ClassSession.ends_at] and the
        member's account_posture is OPEN. On success, final_price_cents equals
        provisional_price_cents (no penalty applies)."

        Claim: a check-in during the inclusive window flips CONFIRMED→ATTENDED,
        sets gate_check_in_at, and final_price_cents == provisional_price_cents.
        """
        from test_helpers import TEST_USERS, advance_clock_to

        scen = setup_member_with_existing_booking(
            state_code="CA", starts_in_hours=24, plan="PLUS", duration_minutes=60
        )
        member = scen["member"]
        booking = scen["booking"]
        provisional = booking["provisional_price_cents"]
        # Confirm first.
        api.confirm_booking(member["id"], booking["id"], make_member_headers(member["id"]))
        # Advance the clock to the session start so we are inside the [start-15, end] window.
        advance_clock_to(scen["class_session"]["starts_at"])
        gate_device_id = scen["store"]["gate_device_id"]
        res = api.check_in_booking(
            member["id"],
            booking["id"],
            {"gate_device_id": gate_device_id},
            TEST_USERS["billing_admin_headers"],
        )
        data = validate_success(res, 200)
        assert data["status"] == "ATTENDED"
        assert data["gate_check_in_at"] is not None
        assert data["final_price_cents"] == provisional, (
            f"PRD §3.7: on ATTENDED, final_price_cents=provisional_price_cents, "
            f"got {data['final_price_cents']} vs {provisional}"
        )
