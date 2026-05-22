"""Booking creation: capacity routing, validation gates, cross-store and tier (PRD §3.6)."""

import pytest

from test_helpers import (
    assert_booking,
    create_booking_for_member,
    create_booking_payload,
    freeze_member_via_delinquency,
    get_class_session_fresh,
    hours_from_now_iso,
    make_member_headers,
    register_member,
    schedule_class_session,
    setup_active_member_with_subscription,
    setup_basic_scenario,
    setup_member_with_existing_booking,
    setup_trainer_with_pt_booking,
    validate_error,
    validate_success,
)


class TestCapacityRouting:

    def test_first_booking_goes_to_reserved_and_increments_seat_count(self, api):
        """PRD §3.6: "If the count is below capacity, the booking is assigned status
        RESERVED, reserved_seat_count is incremented, and waitlist_position is null."

        Claim: first booking on a session with capacity>0 is RESERVED with
        waitlist_position null and reserved_seat_count incremented.
        """
        scen = setup_basic_scenario(state_code="CA", capacity=2)
        booking = create_booking_for_member(
            scen["member"], booking_kind="GROUP_CLASS", class_session=scen["class_session"]
        )
        assert_booking(booking)
        assert booking["status"] == "RESERVED"
        assert booking["waitlist_position"] is None
        session = get_class_session_fresh(scen["store"]["id"], scen["class_session"]["id"])
        assert session["reserved_seat_count"] == 1

    def test_full_capacity_routes_to_waitlist_with_position(self, api):
        """PRD §3.6: "If the count is already at capacity, the booking is assigned
        status WAITLISTED and given the next waitlist_position — a 1-indexed FIFO
        rank computed from Booking.created_at ascending within the same session,
        with ties never broken by id."

        Claim: a booking on a session at capacity is WAITLISTED with
        waitlist_position == 1 for the first overflow.
        """
        scen = setup_basic_scenario(state_code="CA", capacity=1)
        # First member reserves.
        first_member, _ = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        first_booking = create_booking_for_member(
            first_member,
            booking_kind="GROUP_CLASS",
            class_session=scen["class_session"],
        )
        assert first_booking["status"] == "RESERVED"
        # Second member is forced to waitlist.
        second_member, _ = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        second_booking = create_booking_for_member(
            second_member,
            booking_kind="GROUP_CLASS",
            class_session=scen["class_session"],
        )
        assert second_booking["status"] == "WAITLISTED"
        assert second_booking["waitlist_position"] == 1


class TestPostureGate:

    def test_frozen_member_cannot_book(self, api):
        """PRD §3.6: "The member's account_posture must be OPEN for a new RESERVED
        or CONFIRMED seat (a RESTRICTED posture allows a waitlist join only; a
        FROZEN posture rejects entirely with ERR_ACCOUNT_POSTURE_FROZEN)."

        Claim: FROZEN posture booking attempt → ERR_ACCOUNT_POSTURE_FROZEN.
        """
        # Build a FROZEN member first (this advances the server clock past the
        # grace window). Then schedule the class session, so its starts_at is
        # still in the future per the server clock — otherwise the priority-4
        # state-precondition check on the ClassSession fires before the
        # priority-5 posture gate (PRD §2.13).
        frozen_member, _sub = freeze_member_via_delinquency(state_code="CA", plan="PLUS")
        scen = setup_basic_scenario(state_code="CA")
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


class TestMinimumTier:

    def test_basic_member_rejected_for_elite_only_class(self, api):
        """PRD §3.6: "The session's minimum_tier must be at or below the member's
        tier; for instance, a BASIC member who attempts to reserve a PLUS-only or
        ELITE-only class is rejected with ERR_TIER_BELOW_MINIMUM."

        Claim: BASIC member booking an ELITE-only ClassSession → ERR_TIER_BELOW_MINIMUM.
        """
        scen = setup_basic_scenario(state_code="CA")
        elite_session = schedule_class_session(
            scen["store"],
            scen["trainer"],
            class_type="YOGA",
            capacity=5,
            minimum_tier="ELITE",
            starts_in_hours=48,
        )
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
        validate_error(res, "ERR_TIER_BELOW_MINIMUM")


class TestMemberTimeConflict:

    def test_overlapping_booking_rejected(self, api):
        """PRD §3.6: "The booking must not time-conflict with any other booking of
        the same member: the requested [starts_at, ends_at) half-open interval
        must not overlap any of the member's other bookings (across all stores),
        although adjacent intervals (the new booking's starts_at exactly equal to
        another's ends_at, or vice versa) are explicitly permitted; an overlap is
        rejected with ERR_MEMBER_TIME_CONFLICT."

        Claim: a second booking whose interval strictly overlaps an existing
        booking → ERR_MEMBER_TIME_CONFLICT.
        """
        scen = setup_member_with_existing_booking(
            state_code="CA",
            starts_in_hours=48,
            duration_minutes=60,
            plan="PLUS",
            capacity=10,
        )
        member = scen["member"]
        existing = scen["class_session"]
        # Create a second session that overlaps the first by 30 minutes.
        overlap_start = existing["starts_at"]
        # Re-schedule a session at exact overlap.
        overlap_session = schedule_class_session(
            scen["store"],
            scen["trainer"],
            class_type="HIIT",
            starts_at=overlap_start,
            ends_at=existing["ends_at"],
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

    def test_adjacent_back_to_back_bookings_allowed(self, api):
        """PRD §3.6: "...adjacent intervals (the new booking's starts_at exactly
        equal to another's ends_at, or vice versa) are explicitly permitted..."

        Claim: booking starting exactly when another ends → accepted (RESERVED or
        WAITLISTED depending on capacity).
        """
        scen = setup_member_with_existing_booking(
            state_code="CA",
            starts_in_hours=48,
            duration_minutes=60,
            plan="PLUS",
            capacity=10,
        )
        member = scen["member"]
        existing = scen["class_session"]
        # Adjacent session starts when the existing one ends.
        from datetime import datetime, timedelta, timezone

        existing_end = datetime.fromisoformat(existing["ends_at"].replace("Z", "+00:00"))
        adj_session = schedule_class_session(
            scen["store"],
            scen["trainer"],
            class_type="YOGA",
            starts_at=existing["ends_at"],
            ends_at=(existing_end + timedelta(minutes=60)).strftime(
                "%Y-%m-%dT%H:%M:%S.000Z"
            ),
            capacity=10,
        )
        payload = create_booking_payload(
            booking_kind="GROUP_CLASS",
            class_session_id=adj_session["id"],
            starts_at=adj_session["starts_at"],
            ends_at=adj_session["ends_at"],
        )
        res = api.create_booking(member["id"], payload, make_member_headers(member["id"]))
        data = validate_success(res, 201)
        assert data["status"] in ("RESERVED", "WAITLISTED")


class TestTrainerEnvelope:

    def test_pt_booking_adjacent_to_existing_pt_rejected_due_to_15min_envelope(self, api):
        """PRD §3.6: "For personal training, the trainer must be free in the
        closed-on-both-sides envelope of [starts_at − 15 minutes, ends_at + 15
        minutes]; another RESERVED or CONFIRMED PT booking for the same trainer
        that touches this envelope at any point — including the boundary instants
        — is a conflict and is rejected with ERR_TRAINER_UNAVAILABLE."

        Claim: a PT booking starting exactly at the existing PT's ends_at falls
        inside the [-15min, +15min] envelope and is rejected with ERR_TRAINER_UNAVAILABLE.
        """
        from datetime import datetime, timedelta, timezone

        scen = setup_trainer_with_pt_booking(
            state_code="CA", starts_in_hours=48, duration_minutes=30, plan="PLUS"
        )
        existing_end = datetime.fromisoformat(scen["ends_at"].replace("Z", "+00:00"))
        # New PT booking starting at the existing one's end — adjacency within envelope.
        new_member, _ = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        adj_start = scen["ends_at"]
        adj_end = (existing_end + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = create_booking_payload(
            booking_kind="PERSONAL_TRAINING",
            trainer_id=scen["trainer"]["id"],
            starts_at=adj_start,
            ends_at=adj_end,
        )
        res = api.create_booking(
            new_member["id"], payload, make_member_headers(new_member["id"])
        )
        validate_error(res, "ERR_TRAINER_UNAVAILABLE")


class TestLeadTime:

    def test_group_class_must_match_session_starts_at_exactly(self, api):
        """PRD §3.6: "For group classes, the booking's starts_at must be at least
        the minimum lead time — ten minutes — beyond the present clock and must
        equal the underlying ClassSession.starts_at exactly; a violation is
        rejected with ERR_BOOKING_LEAD_TIME."

        Claim: a GROUP_CLASS booking whose starts_at does NOT equal the session's
        starts_at → ERR_BOOKING_LEAD_TIME.
        """
        from datetime import datetime, timedelta, timezone

        scen = setup_basic_scenario(state_code="CA", capacity=5)
        member = scen["member"]
        session = scen["class_session"]
        session_start = datetime.fromisoformat(session["starts_at"].replace("Z", "+00:00"))
        wrong_start = (session_start + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = create_booking_payload(
            booking_kind="GROUP_CLASS",
            class_session_id=session["id"],
            starts_at=wrong_start,
            ends_at=session["ends_at"],
        )
        res = api.create_booking(member["id"], payload, make_member_headers(member["id"]))
        validate_error(res, "ERR_BOOKING_LEAD_TIME")
