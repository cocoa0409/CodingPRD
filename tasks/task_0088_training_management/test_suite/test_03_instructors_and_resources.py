"""Instructors, availability, classrooms, and online rooms (PRD §3.2, §3.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_classroom,
    assert_instructor,
    assert_instructor_availability,
    assert_online_room,
    blacklist_existing_instructor,
    blacklist_instructor_payload,
    create_classroom_payload,
    create_instructor,
    create_instructor_availability_payload,
    create_instructor_payload,
    create_online_room_payload,
    update_instructor_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Instructor creation + INTERNAL zero-rate rule (PRD §3.2)
# ===========================================================================
class TestInstructorCreate:

    def test_external_instructor_carries_non_zero_rates(
        self, api, training_admin_headers,
    ):
        """PRD §3.2: "External instructors carry positive rates and a
        flat per-session travel cost."

        Claim: creating an EXTERNAL instructor with hourly_rate=200,
        travel_cost=50 succeeds and the fields are echoed.
        """
        payload = create_instructor_payload(
            instructor_type="EXTERNAL",
            hourly_rate=200.00, travel_cost=50.00,
            expertise_tags=["engineering"],
        )
        resp = api.create_instructor(payload, training_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_instructor(data)
        assert data["instructor_type"] == "EXTERNAL"
        assert data["status"] == "ACTIVE"
        assert float(data["hourly_rate"]) == 200.00
        assert float(data["travel_cost"]) == 50.00

    def test_internal_instructor_must_have_zero_hourly_rate(
        self, api, training_admin_headers,
    ):
        """PRD §3.2: "Internal instructors must have an hourly_rate of
        zero and a travel_cost of zero — internal time is tracked but
        never paid out."

        Claim: an INTERNAL instructor created via the API has
        hourly_rate=0 and travel_cost=0. The PRD requires these to be
        zero; whether implementations enforce or coerce, the resulting
        row MUST observe the invariant.
        """
        payload = create_instructor_payload(
            instructor_type="INTERNAL",
            hourly_rate=0.0, travel_cost=0.0,
            expertise_tags=["engineering"],
        )
        resp = api.create_instructor(payload, training_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_instructor(data)
        assert float(data["hourly_rate"]) == 0.0
        assert float(data["travel_cost"]) == 0.0


# ===========================================================================
# Roster state transitions (PRD §3.2)
# ===========================================================================
class TestInstructorRoster:

    def test_blacklist_advances_active_to_blacklisted(
        self, api, training_admin_headers,
    ):
        """PRD §3.2: "An instructor's roster status begins as ACTIVE
        and may move to BLACKLISTED or RETIRED. Blacklisting requires
        a non-empty blacklist_reason."

        Claim: POST /blacklist with a reason moves ACTIVE -> BLACKLISTED.
        """
        instructor = create_instructor()
        resp = api.blacklist_instructor(
            instructor["id"],
            blacklist_instructor_payload(blacklist_reason="Misconduct"),
            training_admin_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "BLACKLISTED"
        assert data.get("blacklist_reason") == "Misconduct"

    def test_reinstate_moves_blacklisted_to_active(
        self, api, training_admin_headers,
    ):
        """PRD §3.2: "reinstating returns the instructor to ACTIVE and
        may be performed by a TrainingAdmin."

        Claim: POST /reinstate moves BLACKLISTED -> ACTIVE.
        """
        instructor = create_instructor()
        blacklist_existing_instructor(instructor["id"], reason="x")
        resp = api.reinstate_instructor(instructor["id"], training_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "ACTIVE"


# ===========================================================================
# Availability windows (PRD §3.2)
# ===========================================================================
class TestInstructorAvailability:

    def test_available_window_is_created(self, api, training_admin_headers):
        """PRD §3.2: "Each row carries an instructor_id, a start_at
        (inclusive) and an end_at (strictly after start_at, exclusive),
        and a kind of either AVAILABLE or BLOCKED."

        Claim: a successful POST /availabilities returns the row with
        kind=AVAILABLE.
        """
        instructor = create_instructor()
        payload = create_instructor_availability_payload(
            start_at="2026-06-01T08:00:00.000Z",
            end_at="2026-06-01T18:00:00.000Z",
            kind="AVAILABLE",
        )
        resp = api.create_instructor_availability(
            instructor["id"], payload, training_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_instructor_availability(data)
        assert data["kind"] == "AVAILABLE"


# ===========================================================================
# Classroom creation (PRD §3.3)
# ===========================================================================
class TestClassroom:

    def test_classroom_default_setup_buffer_minutes(
        self, api, training_admin_headers,
    ):
        """PRD §3.3: "a setup_buffer_minutes (default 30, between 0
        and 240 inclusive) representing the minimum gap that must
        elapse after one session in this classroom before another may
        start."

        Claim: omitting setup_buffer_minutes produces a row with
        setup_buffer_minutes=30.
        """
        payload = create_classroom_payload(name="Room-DefaultBuf-1")
        # Drop the explicit default so we exercise the server default.
        payload.pop("setup_buffer_minutes", None)
        resp = api.create_classroom(payload, training_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_classroom(data)
        assert data["setup_buffer_minutes"] == 30


# ===========================================================================
# Online room creation (PRD §3.3)
# ===========================================================================
class TestOnlineRoom:

    def test_online_room_carries_max_participants(
        self, api, training_admin_headers,
    ):
        """PRD §3.3: "It carries a platform (such as zoom or teams),
        a static join_url, a max_participants cap of at least one, and
        a status of ACTIVE or RETIRED."

        Claim: a created online room has max_participants set and
        status defaulting to ACTIVE.
        """
        payload = create_online_room_payload(max_participants=200)
        resp = api.create_online_room(payload, training_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_online_room(data)
        assert data["max_participants"] == 200
        assert data["status"] == "ACTIVE"
