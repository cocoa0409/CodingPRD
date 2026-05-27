"""Resource temporal-overlap conflicts: binary half-open overlap on
GamingSession (touching allowed, strict intersection rejected) and
aggregate-capacity occupancy at Property for CompRoomBooking (cap=20)."""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    set_clock,
    create_property,
    create_member,
    record_gaming_session,
    get_member_version,
    create_booking,
    promote_member_to_platinum,
    ApiErrorId,
    make_loyalty_manager_headers,
    make_member_services_headers,
    bootstrap_property_with_n_overlapping_bookings,
)


class TestGamingSessionBinaryHalfOpenOverlap:
    """PRD §3.3: GamingSession overlap is binary — [started_at, ended_at)
    is half-open, so touching at endpoints is allowed but true intersection
    is rejected with ERR_SESSION_OVERLAP."""

    def test_strictly_overlapping_session_is_rejected(self, api):
        """PRD §3.3: "or if the half-open interval from started_at
        (inclusive) to ended_at (exclusive) truly overlaps an existing
        RECORDED session for the same member on the same property —
        touching at an endpoint is allowed, true overlap is rejected with
        ERR_SESSION_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/gaming_session_binary_half_open_overlap_on_member_property
        """
        set_clock("2026-03-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="M Ov", email="mov@x.com",
        )
        record_gaming_session(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-03-01T10:00:00Z",
            ended_at="2026-03-01T11:00:00Z",
            game_type="SLOTS", theoretical_loss_cents=100000,
        )
        # Strictly overlapping [10:30, 11:30) intersects [10:00, 11:00).
        resp = api.create_gaming_session(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "started_at": "2026-03-01T10:30:00Z",
                "ended_at": "2026-03-01T11:30:00Z",
                "game_type": "SLOTS", "theoretical_loss_cents": 100000,
            },
            make_member_services_headers("ms_1"),
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP.value)

    def test_touching_session_at_endpoint_is_allowed(self, api):
        """PRD §3.3: "touching at an endpoint is allowed, true overlap is
        rejected with ERR_SESSION_OVERLAP."

        Half-open semantics: [10:00, 11:00) and [11:00, 12:00) share the
        single point 11:00, but the first is exclusive of it. No true
        overlap, so the second session must be accepted.

        Design: Difficulty/resource_temporal_overlap/gaming_session_binary_half_open_overlap_on_member_property
        """
        set_clock("2026-03-02T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="M Touch", email="mtouch@x.com",
        )
        record_gaming_session(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-03-02T10:00:00Z",
            ended_at="2026-03-02T11:00:00Z",
            game_type="SLOTS", theoretical_loss_cents=100000,
        )
        # Touching at endpoint: next starts at exactly 11:00.
        resp = api.create_gaming_session(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "started_at": "2026-03-02T11:00:00Z",
                "ended_at": "2026-03-02T12:00:00Z",
                "game_type": "SLOTS", "theoretical_loss_cents": 100000,
            },
            make_member_services_headers("ms_1"),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "RECORDED"


class TestCompRoomBookingAggregateCapacityOverlap:
    """PRD §3.6: CompRoomBooking overlap is aggregate-capacity — exceeding
    the property's occupancy cap of 20 across an interval intersection is
    rejected with ERR_BOOKING_OVERLAP."""

    def test_twenty_first_overlapping_booking_is_rejected(self, api):
        """PRD §3.6: "or if the half-open interval from check_in
        (inclusive) to check_out (exclusive) intersects with other
        non-terminal bookings (PENDING, CONFIRMED, or CHECKED_IN) at the
        same property such that the aggregate count of overlapping
        bookings at any point of intersection would exceed the property's
        occupancy cap of twenty — that aggregate-capacity overlap is
        refused with ERR_BOOKING_OVERLAP (this is distinct from the binary
        touching-vs-overlap rule on gaming sessions; here the rejection
        is about exceeding capacity across the interval intersection)."

        Design: Difficulty/resource_temporal_overlap/comp_room_booking_aggregate_capacity_overlap_at_property
        """
        ctx = bootstrap_property_with_n_overlapping_bookings(
            n=20,
            clock="2026-12-01T00:00:00Z",
            check_in="2027-01-10T15:00:00Z",
            check_out="2027-01-12T11:00:00Z",
        )
        assert len(ctx["bookings"]) == 20
        # 21st member tries to book the same overlapping window.
        m21 = create_member(
            property_id=ctx["property"]["id"],
            full_name="M 21", email="m21@x.com",
        )
        promote_member_to_platinum(
            member_id=m21["id"], property_id=ctx["property"]["id"],
            started_at="2026-12-01T22:00:00Z",
            ended_at="2026-12-01T23:00:00Z",
        )
        v = get_member_version(m21["id"])
        resp = api.create_comp_room_booking(
            {
                "member_id": m21["id"],
                "property_id": ctx["property"]["id"],
                "check_in": "2027-01-10T15:00:00Z",
                "check_out": "2027-01-12T11:00:00Z",
                "expected_member_version": v,
            },
            make_loyalty_manager_headers("lm_1"),
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_OVERLAP.value)

    def test_twentieth_overlapping_booking_at_cap_is_accepted(self, api):
        """PRD §3.6: "the aggregate count of overlapping bookings at any
        point of intersection would exceed the property's occupancy cap of
        twenty — that aggregate-capacity overlap is refused with
        ERR_BOOKING_OVERLAP".

        At exactly the cap (20 overlapping bookings already present and a
        new request also overlapping makes it 21 — that's the rejection
        line), so 20 inserts must each be accepted, with rejection only at
        the 21st.

        Design: Difficulty/resource_temporal_overlap/comp_room_booking_aggregate_capacity_overlap_at_property
        """
        # Build up to exactly 19 bookings and accept the 20th — exhausting
        # the cap without exceeding it.
        ctx = bootstrap_property_with_n_overlapping_bookings(
            n=19,
            clock="2026-12-05T00:00:00Z",
            check_in="2027-02-10T15:00:00Z",
            check_out="2027-02-12T11:00:00Z",
        )
        assert len(ctx["bookings"]) == 19
        m20 = create_member(
            property_id=ctx["property"]["id"],
            full_name="M 20", email="m20cap@x.com",
        )
        promote_member_to_platinum(
            member_id=m20["id"], property_id=ctx["property"]["id"],
            started_at="2026-12-05T22:00:00Z",
            ended_at="2026-12-05T23:00:00Z",
        )
        v = get_member_version(m20["id"])
        resp = api.create_comp_room_booking(
            {
                "member_id": m20["id"],
                "property_id": ctx["property"]["id"],
                "check_in": "2027-02-10T15:00:00Z",
                "check_out": "2027-02-12T11:00:00Z",
                "expected_member_version": v,
            },
            make_loyalty_manager_headers("lm_1"),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PENDING"
