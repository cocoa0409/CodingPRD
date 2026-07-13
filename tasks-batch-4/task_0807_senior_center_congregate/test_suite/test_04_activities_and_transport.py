"""Rooms, activity sessions and signups, vehicles and transportation requests:
room half-open overlap, vehicle buffered turnaround, the cross-entity approval
dependency, signup preconditions, and list pagination.

Translates queue A instances rt_room_half_open_adjacency_allowed,
rt_vehicle_buffered_turnaround, ce_transport_approve_requires_session_scheduled,
plus queue B corner instances for time windows, duplicates, capacity, transport
completion order, and pagination envelopes.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    fixtures,
    factories as F,
)

ADMIN = TEST_USERS["center_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap/rt_room_half_open_adjacency_allowed
# ---------------------------------------------------------------------------
def test_room_interior_overlap_rejected(api):
    """PRD 3.4: "if the new session's half-open interval — inclusive of `starts_at`, exclusive of `ends_at` — overlaps the interval of any existing `SCHEDULED` session in the same room, the request is rejected with `ERR_ROOM_DOUBLE_BOOKED` (409)."

    Design: Difficulty/resource_temporal_overlap/rt_room_half_open_adjacency_allowed
    """
    room = fixtures.create_room(capacity=30)
    fixtures.create_session(
        room["id"], title="Yoga", starts_at="2026-03-11T10:00:00Z",
        ends_at="2026-03-11T11:00:00Z", capacity=10,
    )
    resp = api.create_session(
        F.create_session_payload(
            room_id=room["id"], title="Overlap",
            starts_at="2026-03-11T10:30:00Z", ends_at="2026-03-11T11:30:00Z", capacity=10,
        ),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value)


def test_room_adjacent_session_allowed(api):
    """PRD 3.4: "Because the interval is half-open, a session that begins exactly when another ends (adjacency at the shared boundary) does not overlap and is allowed."

    Design: Difficulty/resource_temporal_overlap/rt_room_half_open_adjacency_allowed
    """
    room = fixtures.create_room(capacity=30)
    fixtures.create_session(
        room["id"], title="Yoga", starts_at="2026-03-11T10:00:00Z",
        ends_at="2026-03-11T11:00:00Z", capacity=10,
    )
    data = validate_success(
        api.create_session(
            F.create_session_payload(
                room_id=room["id"], title="Chair Aerobics",
                starts_at="2026-03-11T11:00:00Z", ends_at="2026-03-11T12:00:00Z", capacity=10,
            ),
            COORD,
        ),
        expected_status=201,
    )
    assert data["status"] == "SCHEDULED", f"adjacent session must be created, got {data['status']}"


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap/rt_vehicle_buffered_turnaround
# ---------------------------------------------------------------------------
def test_vehicle_trip_within_turnaround_buffer_rejected(api):
    """PRD 3.5: "A vehicle cannot be in two places at once, and it needs turnaround time between trips: the new trip window, expanded by a fifteen-minute turnaround buffer on each side, must not overlap any existing non-`CANCELLED` trip already assigned to that vehicle; an overlap is rejected with `ERR_VEHICLE_UNAVAILABLE` (409)."

    Design: Difficulty/resource_temporal_overlap/rt_vehicle_buffered_turnaround
    """
    participant = fixtures.create_participant()
    room = fixtures.create_room(capacity=30)
    vehicle = fixtures.create_vehicle(seat_capacity=6)
    session = fixtures.create_session(
        room["id"], title="Lunch Outing", starts_at="2026-03-14T09:00:00Z",
        ends_at="2026-03-14T12:00:00Z", capacity=20,
    )
    fixtures.create_transport(
        participant["id"], vehicle["id"], session["id"],
        starts_at="2026-03-14T10:00:00Z", ends_at="2026-03-14T10:30:00Z",
    )
    # New trip [10:40,11:00] is only 10 minutes after the first — inside the 15-min buffer.
    resp = api.create_transport(
        F.create_transport_payload(
            participant_id=participant["id"], vehicle_id=vehicle["id"],
            linked_session_id=session["id"],
            starts_at="2026-03-14T10:40:00Z", ends_at="2026-03-14T11:00:00Z",
        ),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_VEHICLE_UNAVAILABLE.value)


def test_vehicle_trip_clear_of_buffer_allowed(api):
    """PRD 3.5: "A vehicle cannot be in two places at once, and it needs turnaround time between trips: the new trip window, expanded by a fifteen-minute turnaround buffer on each side, must not overlap any existing non-`CANCELLED` trip already assigned to that vehicle; an overlap is rejected with `ERR_VEHICLE_UNAVAILABLE` (409)."

    Design: Difficulty/resource_temporal_overlap/rt_vehicle_buffered_turnaround
    """
    participant = fixtures.create_participant()
    room = fixtures.create_room(capacity=30)
    vehicle = fixtures.create_vehicle(seat_capacity=6)
    session = fixtures.create_session(
        room["id"], title="Lunch Outing", starts_at="2026-03-14T09:00:00Z",
        ends_at="2026-03-14T12:00:00Z", capacity=20,
    )
    fixtures.create_transport(
        participant["id"], vehicle["id"], session["id"],
        starts_at="2026-03-14T10:00:00Z", ends_at="2026-03-14T10:30:00Z",
    )
    # New trip [11:00,11:30] is 30 minutes clear — beyond the 15-min buffer on each side.
    data = validate_success(
        api.create_transport(
            F.create_transport_payload(
                participant_id=participant["id"], vehicle_id=vehicle["id"],
                linked_session_id=session["id"],
                starts_at="2026-03-14T11:00:00Z", ends_at="2026-03-14T11:30:00Z",
            ),
            COORD,
        ),
        expected_status=201,
    )
    assert data["trip_status"] == "SCHEDULED", f"clear trip must be scheduled, got {data['trip_status']}"


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency/ce_transport_approve_requires_session_scheduled
# ---------------------------------------------------------------------------
def test_approve_transport_with_cancelled_session_rejected(api):
    """PRD 3.5: "it is permitted only while `eligibility_status` is `PENDING`, and it additionally requires that the linked activity session still be `SCHEDULED` — if that session has been cancelled, approval is rejected with `ERR_SESSION_NOT_SCHEDULED` (409)."

    Design: Difficulty/cross_entity_state_dependency/ce_transport_approve_requires_session_scheduled
    """
    ctx = fixtures.setup_scheduled_transport()
    fixtures.cancel_session(ctx["session"]["id"])
    resp = api.approve_transport(ctx["transport"]["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_SCHEDULED.value)


def test_approve_transport_with_scheduled_session_succeeds(api):
    """PRD 3.5: "Approving the ride's eligibility advances `eligibility_status` from `PENDING` to `APPROVED` and leaves `trip_status` unchanged; it is permitted only while `eligibility_status` is `PENDING`, and it additionally requires that the linked activity session still be `SCHEDULED`".

    Design: Difficulty/cross_entity_state_dependency/ce_transport_approve_requires_session_scheduled
    """
    ctx = fixtures.setup_scheduled_transport()
    data = validate_success(api.approve_transport(ctx["transport"]["id"], COORD))
    assert data["eligibility_status"] == "APPROVED", f"expected APPROVED, got {data['eligibility_status']}"
    assert data["trip_status"] == "SCHEDULED", (
        f"approving eligibility must leave trip_status unchanged, got {data['trip_status']}"
    )


# ---------------------------------------------------------------------------
# Queue B — session/signup/transport preconditions and listing
# ---------------------------------------------------------------------------
def test_session_invalid_time_window_rejected(api):
    """PRD 3.4: "The `starts_at` must be strictly before the `ends_at`; if it is not, the request is rejected with `ERR_INVALID_TIME_WINDOW` (422)."

    Design: Corner/validations/corner_session_invalid_time_window_rejected
    """
    room = fixtures.create_room(capacity=10)
    resp = api.create_session(
        F.create_session_payload(
            room_id=room["id"], title="Bad Window",
            starts_at="2026-03-10T11:00:00Z", ends_at="2026-03-10T10:00:00Z", capacity=5,
        ),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW.value)


def test_duplicate_signup_same_session_rejected(api):
    """PRD 3.4: "A participant may not hold two active signups for the same session; if the participant already holds a `CONFIRMED` signup for that session, the request is rejected with `ERR_DUPLICATE_SIGNUP` (409)."

    Design: Corner/validations/corner_duplicate_signup_same_session_rejected
    """
    fixtures.set_clock("2026-03-01T00:00:00Z")
    participant = fixtures.create_participant()
    room = fixtures.create_room(capacity=20)
    session = fixtures.create_session(
        room["id"], title="Painting", starts_at="2026-03-10T10:00:00Z",
        ends_at="2026-03-10T11:00:00Z", capacity=10,
    )
    fixtures.create_signup(session["id"], participant["id"])
    resp = api.create_signup(
        F.create_signup_payload(session_id=session["id"], participant_id=participant["id"]),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SIGNUP.value)


def test_signup_full_session_before_start_returns_session_full(api):
    """PRD 3.4: "The session must have room: if its `enrolled_count` is already at or above its `capacity`, the signup is rejected with `ERR_SESSION_FULL` (409)."

    Design: Corner/validations/corner_session_full_before_start_returns_session_full
    """
    fixtures.set_clock("2026-03-01T00:00:00Z")
    p1 = fixtures.create_participant()
    p2 = fixtures.create_participant()
    room = fixtures.create_room(capacity=20)
    session = fixtures.create_session(
        room["id"], title="Book Club", starts_at="2026-03-10T10:00:00Z",
        ends_at="2026-03-10T11:00:00Z", capacity=1,
    )
    fixtures.create_signup(session["id"], p1["id"])
    resp = api.create_signup(
        F.create_signup_payload(session_id=session["id"], participant_id=p2["id"]),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL.value)


def test_complete_transport_before_approval_rejected(api):
    """PRD 3.5: "Completing the ride advances `trip_status` from `SCHEDULED` to `COMPLETED` and leaves `eligibility_status` unchanged; it is permitted only while `trip_status` is `SCHEDULED` and only once the ride's `eligibility_status` is already `APPROVED`."

    Design: Corner/state_machines/corner_transport_complete_before_approve_invalid_state
    """
    ctx = fixtures.setup_scheduled_transport()
    resp = api.complete_transport(ctx["transport"]["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_list_activity_sessions_pagination_envelope(api):
    """PRD 2.3: "Each list response includes, inside `meta`, the effective `limit`, the effective `offset`, the `total_count` of records matching the filter before pagination, and a `has_more` boolean that is true when records beyond the current page remain."

    Design: Corner/endpoints/corner_list_activity_sessions_pagination_envelope
    """
    room = fixtures.create_room(capacity=20)
    fixtures.create_session(
        room["id"], title="AM Class", starts_at="2026-03-09T09:00:00Z",
        ends_at="2026-03-09T10:00:00Z", capacity=10,
    )
    fixtures.create_session(
        room["id"], title="PM Class", starts_at="2026-03-09T14:00:00Z",
        ends_at="2026-03-09T15:00:00Z", capacity=10,
    )
    resp = api.list_sessions(COORD, params={"room_id": room["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit=1 must return one item, got {len(data)}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more True, got {meta['has_more']}"
