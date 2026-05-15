"""Session creation rules and resource-conflict validations (PRD §3.3)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    assert_session,
    blacklist_existing_instructor,
    create_classroom,
    create_instructor,
    create_instructor_availability,
    create_online_room,
    create_session,
    create_session_payload,
    iso_utc,
    setup_off_shelf_course,
    setup_published_course,
    setup_session_environment,
    validate_error,
    validate_success,
)


# ===========================================================================
# Mode / room compatibility (PRD §3.3)
# ===========================================================================
class TestSessionModeCompatibility:

    def test_onsite_requires_classroom_id(self, api, training_admin_headers):
        """PRD §3.3: "an ONSITE session requires a classroom_id and
        forbids an online_room_id."

        Claim: ONSITE with no classroom_id is rejected.
        """
        env = setup_session_environment()
        payload = create_session_payload(
            course_id=env["course"]["id"],
            instructor_id=env["instructor"]["id"],
            mode="ONSITE",
            start_at="2026-06-01T09:00:00.000Z",
            end_at="2026-06-01T13:00:00.000Z",
            enrollment_deadline="2026-05-31T23:00:00.000Z",
            capacity=10,
        )
        # No classroom_id, no online_room_id.
        resp = api.create_session(payload, training_admin_headers)
        assert resp.status_code >= 400, (
            "PRD §3.3: ONSITE session must require a classroom_id; got "
            f"status={resp.status_code}"
        )

    def test_online_requires_online_room_and_forbids_classroom(
        self, api, training_admin_headers,
    ):
        """PRD §3.3: "an ONLINE session requires an online_room_id and
        forbids a classroom_id."

        Claim: ONLINE + classroom_id is rejected.
        """
        env = setup_session_environment()
        payload = create_session_payload(
            course_id=env["course"]["id"],
            instructor_id=env["instructor"]["id"],
            mode="ONLINE",
            classroom_id=env["classroom"]["id"],  # forbidden
            online_room_id=env["online_room"]["id"],
            start_at="2026-06-01T09:00:00.000Z",
            end_at="2026-06-01T13:00:00.000Z",
            enrollment_deadline="2026-05-31T23:00:00.000Z",
            capacity=10,
        )
        resp = api.create_session(payload, training_admin_headers)
        assert resp.status_code >= 400, (
            "PRD §3.3: ONLINE session must forbid classroom_id; got "
            f"status={resp.status_code}"
        )


# ===========================================================================
# Cross-entity: Course must be ON_SHELF to host a session (PRD §3.3)
# ===========================================================================
class TestSessionRequiresOnShelfCourse:

    def test_create_session_for_off_shelf_course_rejected(
        self, api, training_admin_headers,
    ):
        """PRD §3.3: "the parent course must be ON_SHELF or the
        request fails with ERR_COURSE_NOT_ON_SHELF."

        Claim: POST /training/sessions for a Course in OFF_SHELF state
        -> ERR_COURSE_NOT_ON_SHELF.
        """
        env = setup_off_shelf_course()
        payload = create_session_payload(
            course_id=env["course"]["id"],
            instructor_id=env["instructor"]["id"],
            mode="ONSITE",
            classroom_id=env["classroom"]["id"],
            start_at="2026-06-01T09:00:00.000Z",
            end_at="2026-06-01T13:00:00.000Z",
            enrollment_deadline="2026-05-31T23:00:00.000Z",
            capacity=10,
        )
        resp = api.create_session(payload, training_admin_headers)
        validate_error(resp, ApiErrorId.ERR_COURSE_NOT_ON_SHELF.value)


# ===========================================================================
# Instructor expertise overlap (PRD §3.2)
# ===========================================================================
class TestInstructorExpertiseOverlap:

    def test_no_tag_overlap_rejected(self, api, training_admin_headers):
        """PRD §3.2: "Additionally, the instructor's expertise_tags
        must overlap with the course's tags by at least one entry;
        otherwise the assignment is rejected with
        ERR_INSTRUCTOR_EXPERTISE_MISMATCH."

        Claim: instructor whose tags share no element with the
        course's tags -> ERR_INSTRUCTOR_EXPERTISE_MISMATCH.
        """
        course = setup_published_course(tags=["chemistry"])
        # Instructor with disjoint tags.
        instructor = create_instructor(expertise_tags=["literature"])
        create_instructor_availability(
            instructor["id"],
            "2026-06-01T08:00:00.000Z",
            "2026-06-01T18:00:00.000Z",
        )
        classroom = create_classroom()
        payload = create_session_payload(
            course_id=course["id"],
            instructor_id=instructor["id"],
            mode="ONSITE",
            classroom_id=classroom["id"],
            start_at="2026-06-01T09:00:00.000Z",
            end_at="2026-06-01T13:00:00.000Z",
            enrollment_deadline="2026-05-31T23:00:00.000Z",
            capacity=10,
        )
        resp = api.create_session(payload, training_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_EXPERTISE_MISMATCH.value)


# ===========================================================================
# Instructor blacklist gate (PRD §3.2)
# ===========================================================================
class TestInstructorBlacklistGate:

    def test_blacklisted_instructor_rejected_on_session_create(
        self, api, training_admin_headers,
    ):
        """PRD §3.2: "A blacklisted or retired instructor cannot be
        assigned to a session: any session creation or update that
        tries to do so is rejected with ERR_INSTRUCTOR_BLACKLISTED."

        Claim: assigning a BLACKLISTED instructor to a new session ->
        ERR_INSTRUCTOR_BLACKLISTED.
        """
        course = setup_published_course(tags=["engineering"])
        instructor = create_instructor(expertise_tags=["engineering"])
        create_instructor_availability(
            instructor["id"],
            "2026-06-01T08:00:00.000Z",
            "2026-06-01T18:00:00.000Z",
        )
        blacklist_existing_instructor(instructor["id"])
        classroom = create_classroom()
        payload = create_session_payload(
            course_id=course["id"],
            instructor_id=instructor["id"],
            mode="ONSITE",
            classroom_id=classroom["id"],
            start_at="2026-06-01T09:00:00.000Z",
            end_at="2026-06-01T13:00:00.000Z",
            enrollment_deadline="2026-05-31T23:00:00.000Z",
            capacity=10,
        )
        resp = api.create_session(payload, training_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_BLACKLISTED.value)


# ===========================================================================
# Instructor availability windows (PRD §3.2)
# ===========================================================================
class TestInstructorAvailabilityGate:

    def test_no_available_window_rejects_session_create(
        self, api, training_admin_headers,
    ):
        """PRD §3.2: "For a session to be scheduled against an
        instructor, at least one AVAILABLE window must fully cover the
        session's [start_at, end_at) interval ... Failure on either
        side returns ERR_INSTRUCTOR_UNAVAILABLE."

        Claim: an instructor with NO AVAILABLE window cannot host a
        session -> ERR_INSTRUCTOR_UNAVAILABLE.
        """
        course = setup_published_course(tags=["engineering"])
        instructor = create_instructor(expertise_tags=["engineering"])
        # No availability declared.
        classroom = create_classroom()
        payload = create_session_payload(
            course_id=course["id"],
            instructor_id=instructor["id"],
            mode="ONSITE",
            classroom_id=classroom["id"],
            start_at="2026-06-01T09:00:00.000Z",
            end_at="2026-06-01T13:00:00.000Z",
            enrollment_deadline="2026-05-31T23:00:00.000Z",
            capacity=10,
        )
        resp = api.create_session(payload, training_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_UNAVAILABLE.value)

    def test_blocked_window_overlaps_session_rejects(
        self, api, training_admin_headers,
    ):
        """PRD §3.2: "no BLOCKED window may overlap that interval at
        all. Failure on either side returns ERR_INSTRUCTOR_UNAVAILABLE."

        Claim: a BLOCKED window that overlaps the session interval ->
        ERR_INSTRUCTOR_UNAVAILABLE.
        """
        course = setup_published_course(tags=["engineering"])
        instructor = create_instructor(expertise_tags=["engineering"])
        # An AVAILABLE window covers the day.
        create_instructor_availability(
            instructor["id"],
            "2026-06-01T08:00:00.000Z",
            "2026-06-01T18:00:00.000Z",
            kind="AVAILABLE",
        )
        # A BLOCKED window overlaps 10:00-12:00.
        create_instructor_availability(
            instructor["id"],
            "2026-06-01T10:00:00.000Z",
            "2026-06-01T12:00:00.000Z",
            kind="BLOCKED",
        )
        classroom = create_classroom()
        payload = create_session_payload(
            course_id=course["id"],
            instructor_id=instructor["id"],
            mode="ONSITE",
            classroom_id=classroom["id"],
            start_at="2026-06-01T09:00:00.000Z",
            end_at="2026-06-01T13:00:00.000Z",
            enrollment_deadline="2026-05-31T23:00:00.000Z",
            capacity=10,
        )
        resp = api.create_session(payload, training_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_UNAVAILABLE.value)


# ===========================================================================
# Classroom buffered overlap (PRD §3.3) — covers difficulty instance
# resource_temporal_overlap/classroom_buffered_interval_overlap.
# ===========================================================================
class TestClassroomBufferedOverlap:

    def test_overlap_within_setup_buffer_rejected(
        self, api, training_admin_headers,
    ):
        """PRD §3.3: "treat each existing session as occupying the
        half-open window from its start_at to its end_at plus
        setup_buffer_minutes, and treat the candidate the same way; if
        these two windows share any positive duration of overlap, the
        request is rejected with ERR_CLASSROOM_CONFLICT."

        Claim: a second session starting 15 minutes after the first
        ends (inside the 30-minute setup buffer) -> ERR_CLASSROOM_CONFLICT.
        """
        env = setup_session_environment(
            tags=["engineering"], setup_buffer_minutes=30,
            duration_hours=2.0,
        )
        # First session 09:00-11:00 (buffered end = 11:30).
        create_session(
            env["course"], env["instructor"],
            mode="ONSITE", classroom=env["classroom"],
            start_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc),
            enrollment_deadline=datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc),
            capacity=10,
        )
        # Candidate 11:15-13:15 (2h to match course duration) — overlaps the buffer.
        payload = create_session_payload(
            course_id=env["course"]["id"],
            instructor_id=env["instructor"]["id"],
            mode="ONSITE",
            classroom_id=env["classroom"]["id"],
            start_at=iso_utc(datetime(2026, 6, 1, 11, 15, tzinfo=timezone.utc)),
            end_at=iso_utc(datetime(2026, 6, 1, 13, 15, tzinfo=timezone.utc)),
            enrollment_deadline=iso_utc(
                datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc),
            ),
            capacity=10,
        )
        resp = api.create_session(payload, training_admin_headers)
        validate_error(resp, ApiErrorId.ERR_CLASSROOM_CONFLICT.value)

    def test_session_starts_exactly_at_buffer_end_succeeds(
        self, api, training_admin_headers,
    ):
        """PRD §3.3: "treat each existing session as occupying the
        half-open window from its start_at to its end_at plus
        setup_buffer_minutes ... Time intervals are half-open
        [start_at, end_at) and no setup buffer applies to online rooms."

        Claim: half-open semantics mean a second session starting at
        EXACTLY end_at + setup_buffer_minutes does NOT overlap and is
        accepted.

        Note: the existing instructor is reused but with a fresh
        AVAILABLE window covering the longer span.
        """
        env = setup_session_environment(
            tags=["engineering"],
            setup_buffer_minutes=30,
            duration_hours=2.0,
            availability_start=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
            availability_end=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
        )
        # First session 09:00-11:00 (buffered end = 11:30).
        create_session(
            env["course"], env["instructor"],
            mode="ONSITE", classroom=env["classroom"],
            start_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc),
            enrollment_deadline=datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc),
            capacity=10,
        )
        # Candidate 11:30-13:30 (2h) — starts exactly at the buffer end.
        payload = create_session_payload(
            course_id=env["course"]["id"],
            instructor_id=env["instructor"]["id"],
            mode="ONSITE",
            classroom_id=env["classroom"]["id"],
            start_at=iso_utc(datetime(2026, 6, 1, 11, 30, tzinfo=timezone.utc)),
            end_at=iso_utc(datetime(2026, 6, 1, 13, 30, tzinfo=timezone.utc)),
            enrollment_deadline=iso_utc(
                datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc),
            ),
            capacity=10,
        )
        resp = api.create_session(payload, training_admin_headers)
        validate_success(resp, expected_status=201)


# ===========================================================================
# Online-room aggregate-capacity rule (PRD §3.3) — covers difficulty
# instance resource_temporal_overlap/online_room_aggregate_capacity_overlap.
# ===========================================================================
class TestOnlineRoomAggregateCapacity:

    def test_capacity_sum_exceeds_max_participants_rejected(
        self, api, training_admin_headers,
    ):
        """PRD §3.3: "multiple sessions may share the same
        online_room_id in overlapping windows provided that the sum of
        their capacity values at any single point in time does not
        exceed the online room's max_participants ... a violation
        returns ERR_ONLINE_ROOM_CAPACITY_EXCEEDED."

        Claim: existing session capacity=60 + candidate capacity=50 in
        the same online room with overlapping time -> aggregate 110 >
        100 -> ERR_ONLINE_ROOM_CAPACITY_EXCEEDED.
        """
        env = setup_session_environment(
            tags=["engineering"], online_room_max_participants=100,
            duration_hours=2.0,
        )
        create_session(
            env["course"], env["instructor"],
            mode="ONLINE", online_room=env["online_room"],
            start_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc),
            enrollment_deadline=datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc),
            capacity=60,
        )
        # Second course/instructor pair so we don't trip instructor
        # availability/expertise checks.
        env2 = setup_session_environment(
            tags=["engineering"],
            duration_hours=2.0,
            availability_start=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
            availability_end=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
        )
        payload = create_session_payload(
            course_id=env2["course"]["id"],
            instructor_id=env2["instructor"]["id"],
            mode="ONLINE",
            online_room_id=env["online_room"]["id"],
            start_at=iso_utc(datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)),
            end_at=iso_utc(datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)),
            enrollment_deadline=iso_utc(
                datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc),
            ),
            capacity=50,
        )
        resp = api.create_session(payload, training_admin_headers)
        validate_error(resp, ApiErrorId.ERR_ONLINE_ROOM_CAPACITY_EXCEEDED.value)

    def test_capacity_sum_equal_to_max_participants_succeeds(
        self, api, training_admin_headers,
    ):
        """PRD §3.3: "the sum of their capacity values at any single
        point in time does not exceed the online room's max_participants."

        Claim: existing capacity=60 + candidate capacity=40 = 100
        which does NOT exceed 100; session creation succeeds.
        """
        env = setup_session_environment(
            tags=["engineering"], online_room_max_participants=100,
            duration_hours=2.0,
        )
        create_session(
            env["course"], env["instructor"],
            mode="ONLINE", online_room=env["online_room"],
            start_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc),
            enrollment_deadline=datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc),
            capacity=60,
        )
        env2 = setup_session_environment(
            tags=["engineering"],
            duration_hours=2.0,
            availability_start=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
            availability_end=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
        )
        payload = create_session_payload(
            course_id=env2["course"]["id"],
            instructor_id=env2["instructor"]["id"],
            mode="ONLINE",
            online_room_id=env["online_room"]["id"],
            start_at=iso_utc(datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)),
            end_at=iso_utc(datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)),
            enrollment_deadline=iso_utc(
                datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc),
            ),
            capacity=40,
        )
        resp = api.create_session(payload, training_admin_headers)
        validate_success(resp, expected_status=201)


# ===========================================================================
# Session creation success path: pins course version (PRD §2.12, §3.3)
# ===========================================================================
class TestSessionPinsCourseVersion:

    def test_session_pins_current_course_version_at_creation(
        self, api, training_admin_headers,
    ):
        """PRD §2.12: "When a session is created, the system snapshots
        a pointer to the course's currently published version ...
        into the session's pinned_course_version_id. This pointer is
        immutable for the life of the session."

        Claim: a newly created session has a non-empty
        pinned_course_version_id.
        """
        env = setup_session_environment(tags=["engineering"])
        session = create_session(
            env["course"], env["instructor"],
            mode="ONSITE", classroom=env["classroom"],
        )
        assert_session(session)
        assert session["pinned_course_version_id"], (
            "PRD §2.12: pinned_course_version_id must be set at creation"
        )
