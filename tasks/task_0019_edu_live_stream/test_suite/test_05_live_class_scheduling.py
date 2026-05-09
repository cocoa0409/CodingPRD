"""Live class scheduling: room overlap, instructor availability, start/end gates (PRD §3.3)."""

import pytest

from test_helpers import (
    advance_clock,
    api_client,
    assert_live_class,
    create_instructor,
    create_live_class_payload,
    create_published_course,
    delist_course,
    end_live_class,
    make_instructor_headers,
    reschedule_live_class_payload,
    schedule_live_class,
    setup_room_with_existing_session,
    setup_instructor_with_window,
    start_live_class,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestSchedulingHappyPath:
    """PRD §3.3 baseline create."""

    def test_schedule_live_class_lands_in_scheduled(self, api):
        """PRD §3.3: 'The newly created live class lands with
        status = SCHEDULED.'"""
        course, instructor, _ = create_published_course()
        live = schedule_live_class(course, instructor, start_ts=10_000, end_ts=13_600)
        assert_live_class(live)
        assert live["status"] == "SCHEDULED"

    def test_schedule_end_ts_must_be_strictly_greater(self, api):
        """PRD §3.3: 'where end_ts must be strictly greater than start_ts.'

        end_ts == start_ts violates the strict-greater rule.
        """
        course, instructor, _ = create_published_course()
        payload = create_live_class_payload(
            instructor_id=instructor["id"],
            room_id="ROOM-X",
            start_ts=1000, end_ts=1000,
        )
        res = api.create_live_class(
            course["id"], payload, make_instructor_headers(instructor["id"])
        )
        # PRD does not name a specific error_id for this; PRD §2.8 priority 1
        # is auth, priority 16 covers pricing only — the only enumerated
        # priorities that match an end_ts≤start_ts violation is the existence/
        # validation envelope. Per PRD §2.6 envelope, the response must be a
        # 4xx error. We only assert non-2xx here to honour the
        # two-reader rule (PRD does not pin a single error_id).
        assert res.status_code >= 400 and res.status_code < 500, (
            f"end_ts==start_ts must be rejected with 4xx; got {res.status_code}"
        )


class TestRoomOverlap:
    """PRD §3.3: 'Every existing live class on the same room_id ... occupies an
    interval that starts at its own start_ts (inclusive) and ends ten minutes
    — that is, six hundred seconds — after its own end_ts (exclusive). The
    candidate conflicts with any of these occupied intervals if and only if
    the candidate's start_ts is strictly less than the occupied end and the
    candidate's end_ts is strictly greater than the occupied start; any such
    conflict is rejected with ERR_ROOM_CONFLICT.'"""

    def test_overlap_inside_existing_window_rejected(self, api):
        """PRD §3.3: room conflict on overlapping interior."""
        course, instructor, _ = setup_room_with_existing_session(
            room_id="ROOM-A", existing_start_ts=1000, existing_end_ts=2000
        )
        # Candidate [1500, 1800) sits inside [1000, 2000+600)
        res = api.create_live_class(
            course["id"],
            create_live_class_payload(
                instructor["id"], "ROOM-A", start_ts=1500, end_ts=1800
            ),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_ROOM_CONFLICT")

    def test_adjacent_touching_within_buffer_rejected(self, api):
        """PRD §3.3: 'six hundred seconds — after its own end_ts (exclusive).
        The candidate conflicts ... if and only if the candidate's start_ts is
        strictly less than the occupied end.' For occupied ending at 2000+600,
        a candidate at start_ts=2000 has 2000<2600, so it conflicts."""
        course, instructor, _ = setup_room_with_existing_session(
            room_id="ROOM-B", existing_start_ts=1000, existing_end_ts=2000
        )
        res = api.create_live_class(
            course["id"],
            create_live_class_payload(
                instructor["id"], "ROOM-B", start_ts=2000, end_ts=3000
            ),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_ROOM_CONFLICT")

    def test_after_buffer_succeeds(self, api):
        """PRD §3.3: candidate.start_ts == occupied.end_ts + 600 means
        2600 < 2600 is FALSE, so the conflict condition is NOT met — start at
        the buffer's end is allowed."""
        course, instructor, _ = setup_room_with_existing_session(
            room_id="ROOM-C", existing_start_ts=1000, existing_end_ts=2000
        )
        res = api.create_live_class(
            course["id"],
            create_live_class_payload(
                instructor["id"], "ROOM-C", start_ts=2600, end_ts=3600
            ),
            make_instructor_headers(instructor["id"]),
        )
        validate_success(res, expected_status=201)

    def test_room_overlap_one_second_inside_buffer_rejected(self, api):
        """PRD §3.3: 'the candidate's start_ts is strictly less than the
        occupied end' — occupied ends at 2600, so start_ts=2599 conflicts."""
        course, instructor, _ = setup_room_with_existing_session(
            room_id="ROOM-D", existing_start_ts=1000, existing_end_ts=2000
        )
        res = api.create_live_class(
            course["id"],
            create_live_class_payload(
                instructor["id"], "ROOM-D", start_ts=2599, end_ts=3500
            ),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_ROOM_CONFLICT")


class TestInstructorAvailability:
    """PRD §3.3: 'The candidate is admitted if and only if the instructor's
    availability_windows array contains some window such that the window's
    start_ts is less than or equal to the candidate's start_ts and the
    candidate's end_ts is less than or equal to the window's end_ts. Both
    endpoints are inclusive — a candidate whose end_ts is exactly equal to a
    window's end_ts is allowed.'"""

    def test_candidate_within_window_succeeds(self, api):
        """PRD §3.3: standard inside-window acceptance."""
        course, instructor, _ = setup_instructor_with_window(
            window_start=1000, window_end=5000
        )
        res = api.create_live_class(
            course["id"],
            create_live_class_payload(
                instructor["id"], "ROOM-AV1", start_ts=2000, end_ts=4000
            ),
            make_instructor_headers(instructor["id"]),
        )
        validate_success(res, expected_status=201)

    def test_candidate_end_exactly_at_window_end_allowed(self, api):
        """PRD §3.3: 'a candidate whose end_ts is exactly equal to a window's
        end_ts is allowed.'"""
        course, instructor, _ = setup_instructor_with_window(
            window_start=1000, window_end=5000
        )
        res = api.create_live_class(
            course["id"],
            create_live_class_payload(
                instructor["id"], "ROOM-AV2", start_ts=4000, end_ts=5000
            ),
            make_instructor_headers(instructor["id"]),
        )
        validate_success(res, expected_status=201)

    def test_candidate_end_one_after_window_rejected(self, api):
        """PRD §3.3: 'the candidate's end_ts is less than or equal to the
        window's end_ts' — end_ts=5001 against window_end=5000 fails."""
        course, instructor, _ = setup_instructor_with_window(
            window_start=1000, window_end=5000
        )
        res = api.create_live_class(
            course["id"],
            create_live_class_payload(
                instructor["id"], "ROOM-AV3", start_ts=4000, end_ts=5001
            ),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_INSTRUCTOR_UNAVAILABLE")

    def test_candidate_start_before_window_rejected(self, api):
        """PRD §3.3: 'the window's start_ts is less than or equal to the
        candidate's start_ts' — start_ts=999 against window_start=1000 fails."""
        course, instructor, _ = setup_instructor_with_window(
            window_start=1000, window_end=5000
        )
        res = api.create_live_class(
            course["id"],
            create_live_class_payload(
                instructor["id"], "ROOM-AV4", start_ts=999, end_ts=2000
            ),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_INSTRUCTOR_UNAVAILABLE")


class TestStartLiveClassGates:
    """PRD §3.3: 'Starting a live class advances status from SCHEDULED to LIVE.
    The transition requires the parent course's posture to be OPEN (otherwise
    ERR_COURSE_FROZEN), the call to be made by the live class's owning
    instructor (ERR_FORBIDDEN_NOT_OWNER), and the current now_ts to be no
    earlier than ten minutes before the class's start_ts ... an earlier
    attempt is rejected with ERR_LIVE_CLASS_TOO_EARLY.'"""

    def test_start_too_early_rejected(self, api):
        """PRD §3.3: 'the current now_ts to be no earlier than ten minutes
        before the class's start_ts — that is, now_ts must be at least
        start_ts minus six hundred seconds; an earlier attempt is rejected
        with ERR_LIVE_CLASS_TOO_EARLY.'

        Uses a far-future start_ts so the server's current now_ts is
        comfortably before start_ts - 600.
        """
        course, instructor, _ = create_published_course()
        live = schedule_live_class(
            course, instructor,
            start_ts=9_000_000_000, end_ts=9_000_003_600,
        )
        res = api.start_live_class(live["id"], make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_LIVE_CLASS_TOO_EARLY")

    def test_start_within_lead_window_succeeds(self, api):
        """PRD §3.3 sanity: with now_ts advanced into the lead window, start
        succeeds and yields a checkin_code.

        PRD §3.3: 'The transition generates a six-digit alphanumeric
        checkin_code and persists it on the row.'
        """
        course, instructor, _ = create_published_course()
        live = schedule_live_class(
            course, instructor, start_ts=2_000_000, end_ts=2_003_600
        )
        # Advance to start_ts so 'no earlier than start_ts - 600' is satisfied.
        advance_clock(2_000_000)
        started = validate_success(
            api.start_live_class(live["id"], make_instructor_headers(instructor["id"])),
            expected_status=200,
        )
        assert started["status"] == "LIVE"
        code = started.get("checkin_code")
        assert isinstance(code, str) and len(code) == 6, (
            f"checkin_code must be 6-character string, got {code}"
        )

    def test_start_when_course_frozen_rejected(self, api):
        """PRD §3.3: 'The transition requires the parent course's posture to
        be OPEN (otherwise ERR_COURSE_FROZEN).'

        Note: per PRD §3.1, delist cascades CANCEL the SCHEDULED live class.
        To exercise the start-on-frozen path independent of cascade, schedule
        first, delist (which cancels), then attempt to start. Because the
        live class was cancelled by the cascade, the state-priority rule (5)
        could fire ERR_LIVE_CLASS_NOT_SCHEDULED before the posture rule (6).
        However PRD §3.3 also says 'In a race where delist and live-class
        start fire concurrently against a PUBLISHED course ... if delist
        commits first, the start sees a frozen course and is rejected with
        ERR_COURSE_FROZEN.' That race scenario is the one this test covers
        — delist commits first, then start runs.

        Per PRD §2.8 priority order, state (5) precedes posture (6), and the
        PRD does not explicitly name which error wins for a sequential delist
        → start. We accept either outcome as faithful per PRD §2.8 priority.
        """
        from test_helpers import validate_error_is_one_of
        course, instructor, _ = create_published_course()
        live = schedule_live_class(
            course, instructor, start_ts=2_500_000, end_ts=2_503_600
        )
        delist_course(course)  # PUBLISHED → DELISTED, posture FROZEN, live → CANCELLED
        advance_clock(2_500_000)
        res = api.start_live_class(live["id"], make_instructor_headers(instructor["id"]))
        validate_error_is_one_of(res, ["ERR_LIVE_CLASS_NOT_SCHEDULED", "ERR_COURSE_FROZEN"])


class TestEndLiveClass:
    """PRD §3.3: 'Ending a live class advances status from LIVE to ENDED; if
    the live class is not currently LIVE, the call fails with
    ERR_LIVE_CLASS_NOT_LIVE.'"""

    def test_end_not_live_rejected(self, api):
        """PRD §3.3: 'if the live class is not currently LIVE, the call fails
        with ERR_LIVE_CLASS_NOT_LIVE.'"""
        course, instructor, _ = create_published_course()
        live = schedule_live_class(course, instructor, start_ts=3_500_000, end_ts=3_503_600)
        res = api.end_live_class(live["id"], make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_LIVE_CLASS_NOT_LIVE")

    def test_end_live_advances_to_ended(self, api):
        """PRD §3.3: 'Ending a live class advances status from LIVE to ENDED.'"""
        from test_helpers import setup_live_session_in_progress
        course, instructor, student, enrollment, live = setup_live_session_in_progress(
            start_ts=4_500_000, end_ts=4_503_600
        )
        ended = validate_success(
            api.end_live_class(live["id"], make_instructor_headers(instructor["id"])),
            expected_status=200,
        )
        assert ended["status"] == "ENDED"


class TestRescheduleLiveClass:
    """PRD §3.3: 'A live class can also be rescheduled while SCHEDULED ...
    Calling reschedule on a class that is not SCHEDULED fails with
    ERR_LIVE_CLASS_NOT_SCHEDULED.'"""

    def test_reschedule_not_scheduled_rejected(self, api):
        """PRD §3.3: 'Calling reschedule on a class that is not SCHEDULED
        fails with ERR_LIVE_CLASS_NOT_SCHEDULED.'"""
        from test_helpers import setup_live_session_in_progress
        course, instructor, _, _, live = setup_live_session_in_progress(
            start_ts=5_500_000, end_ts=5_503_600
        )
        # live is now LIVE, not SCHEDULED.
        res = api.reschedule_live_class(
            live["id"],
            reschedule_live_class_payload("ROOM-X", 6_000_000, 6_003_600),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_LIVE_CLASS_NOT_SCHEDULED")

    def test_reschedule_creates_makeup_with_back_link(self, api):
        """PRD §3.3: 'The original row's status advances to RESCHEDULED and is
        retained for audit; a new LiveClass row — the makeup class — is
        created with the new triple, and its original_live_class_id is set to
        the original row's id.'"""
        course, instructor, _ = create_published_course()
        live = schedule_live_class(course, instructor, start_ts=7_000_000, end_ts=7_003_600)
        res = api.reschedule_live_class(
            live["id"],
            reschedule_live_class_payload("ROOM-MAKEUP", 8_000_000, 8_003_600),
            make_instructor_headers(instructor["id"]),
        )
        # PRD §4 says reschedule creates a new resource; status code = 201.
        makeup = validate_success(res, expected_status=201)
        assert makeup["original_live_class_id"] == live["id"], (
            f"makeup.original_live_class_id must back-link to original; got {makeup.get('original_live_class_id')}"
        )
