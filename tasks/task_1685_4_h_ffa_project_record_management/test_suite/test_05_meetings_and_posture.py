"""Meeting room overlap (half-open semantics) and the attendance posture boundary."""
from test_helpers import (
    TEST_DEFAULTS,
    assert_meeting,
    build_approved_record_book,
    create_meeting_payload,
    make_member_headers,
    make_volunteer_headers,
    record_attendance_and_hold,
    setup_active_member_with_project,
    setup_club_with_volunteers,
    validate_error,
    validate_success,
)


class TestRoomOverlap:
    def test_touching_meetings_both_allowed(self, api):
        """PRD §3.6: "Two meetings that merely touch, one ending at exactly the
        instant the other begins, do not overlap and are both allowed."

        Design: Difficulty/resource_temporal_overlap/room_booking_half_open_adjacency
        """
        ctx = setup_club_with_volunteers()
        vol_headers = make_volunteer_headers(ctx["vol1"]["id"])
        first = validate_success(
            api.create_meeting(
                create_meeting_payload(
                    ctx["club"]["id"],
                    ctx["room"]["id"],
                    starts_at="2026-06-01T18:00:00Z",
                    ends_at="2026-06-01T19:00:00Z",
                ),
                vol_headers,
            ),
            201,
        )
        assert_meeting(first)
        adjacent = validate_success(
            api.create_meeting(
                create_meeting_payload(
                    ctx["club"]["id"],
                    ctx["room"]["id"],
                    starts_at="2026-06-01T19:00:00Z",
                    ends_at="2026-06-01T20:00:00Z",
                ),
                vol_headers,
            ),
            201,
        )
        assert_meeting(adjacent)
        assert adjacent["status"] == "SCHEDULED", (
            "half-open [start, end) intervals that merely touch must both schedule"
        )

    def test_overlapping_meeting_rejected(self, api):
        """PRD §3.6: "the room may not be double-booked — the new meeting's
        half-open interval, which includes its start and excludes its end, must
        not overlap any existing SCHEDULED or HELD meeting in the same room, on
        pain of `ERR_ROOM_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/room_booking_half_open_adjacency
        """
        ctx = setup_club_with_volunteers()
        vol_headers = make_volunteer_headers(ctx["vol1"]["id"])
        validate_success(
            api.create_meeting(
                create_meeting_payload(
                    ctx["club"]["id"],
                    ctx["room"]["id"],
                    starts_at="2026-06-01T18:00:00Z",
                    ends_at="2026-06-01T19:00:00Z",
                ),
                vol_headers,
            ),
            201,
        )
        res = api.create_meeting(
            create_meeting_payload(
                ctx["club"]["id"],
                ctx["room"]["id"],
                starts_at="2026-06-01T18:30:00Z",
                ends_at="2026-06-01T19:30:00Z",
            ),
            vol_headers,
        )
        validate_error(res, "ERR_ROOM_CONFLICT")

    def test_cancelled_meeting_frees_the_room(self, api):
        """PRD §3.6: "the new meeting's half-open interval, which includes its
        start and excludes its end, must not overlap any existing SCHEDULED or
        HELD meeting in the same room, on pain of `ERR_ROOM_CONFLICT`
        (HTTP 409)."

        A CANCELLED meeting is neither SCHEDULED nor HELD, so an overlapping
        interval is allowed once the earlier meeting is cancelled.

        Design: Difficulty/resource_temporal_overlap/room_booking_half_open_adjacency
        """
        ctx = setup_club_with_volunteers()
        vol_headers = make_volunteer_headers(ctx["vol1"]["id"])
        first = validate_success(
            api.create_meeting(
                create_meeting_payload(
                    ctx["club"]["id"],
                    ctx["room"]["id"],
                    starts_at="2026-06-01T18:00:00Z",
                    ends_at="2026-06-01T19:00:00Z",
                ),
                vol_headers,
            ),
            201,
        )
        cancelled = validate_success(api.cancel_meeting(first["id"], vol_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        overlapping = validate_success(
            api.create_meeting(
                create_meeting_payload(
                    ctx["club"]["id"],
                    ctx["room"]["id"],
                    starts_at="2026-06-01T18:30:00Z",
                    ends_at="2026-06-01T19:30:00Z",
                ),
                vol_headers,
            ),
            201,
        )
        assert overlapping["status"] == "SCHEDULED"


class TestAttendancePostureBoundary:
    def test_attendance_exactly_75_percent_eligible(self, api):
        """PRD §3.7: "The posture is ELIGIBLE when the attendance percentage is
        at least 75 and both documentary conditions hold." PRD §3.7: "The
        threshold boundary is inclusive: an attendance percentage of exactly
        75.00 satisfies it."

        3 PRESENT + 1 ABSENT = 75.00%; with an approved record book and no
        livestock projects, the approve-triggered recompute yields ELIGIBLE.

        Design: Corner/calculations/attendance_exactly_75_percent_eligible
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx)
        record_attendance_and_hold(
            ctx, member["id"], ["PRESENT", "PRESENT", "PRESENT", "ABSENT"]
        )
        build_approved_record_book(
            ctx, member, project, scores=TEST_DEFAULTS["SCORES_80"]
        )
        member_after = validate_success(
            api.get_member(member["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        assert member_after["eligibility_posture"] == "ELIGIBLE", (
            f"exactly 75.00% attendance satisfies the >= 75 threshold, "
            f"got {member_after['eligibility_posture']}"
        )

    def test_attendance_below_75_percent_not_eligible(self, api):
        """PRD §3.7: "The posture is ELIGIBLE when the attendance percentage is
        at least 75 and both documentary conditions hold. It is CONDITIONAL when
        the attendance percentage is at least 75 and exactly one of the two
        documentary conditions holds — an approved record book without the
        required verified tags, or verified tags without an approved record
        book. It is INELIGIBLE in every other case."

        1 PRESENT + 2 ABSENT = 33.33% < 75: even with an approved book the
        posture stays INELIGIBLE.

        Design: Corner/calculations/attendance_exactly_75_percent_eligible
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx)
        record_attendance_and_hold(ctx, member["id"], ["PRESENT", "ABSENT", "ABSENT"])
        build_approved_record_book(ctx, member, project, scores=TEST_DEFAULTS["SCORES_80"])
        member_after = validate_success(
            api.get_member(member["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        assert member_after["eligibility_posture"] == "INELIGIBLE", (
            f"33.33% attendance fails the threshold regardless of the approved book, "
            f"got {member_after['eligibility_posture']}"
        )
