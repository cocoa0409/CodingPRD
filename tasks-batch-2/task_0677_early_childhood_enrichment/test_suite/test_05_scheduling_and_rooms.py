"""Scheduling integrity: instructor buffer/certification, room half-open overlap,
open-gym head-count aggregation, birthday-party exclusivity, booking release,
and session-create request validation.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_program, create_room, create_instructor,
    create_session, create_family,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["studio_admin_headers"]
STAFF = TEST_USERS["front_desk_headers"]


def test_instructor_buffer_overlap_rejects_within_buffer_gap(api):
    """PRD §2.11: "For overlap detection, the instructor's occupied interval for a
    session is the session's [start_at, end_at) expanded by buffer_minutes on each
    side; the expanded interval must not overlap any other non-CANCELLED session of
    the same instructor, or the new session is rejected with
    ERR_INSTRUCTOR_SCHEDULE_CONFLICT (HTTP 409)."

    Instructor with buffer_minutes=15 teaching 09:00-10:00; a second 10:10-11:00
    session (only a 10-minute gap) collides because the 15-minute buffer expands
    the occupied interval.

    Design: Difficulty/resource_temporal_overlap/instructor_buffer_overlap_rejects_within_buffer_gap
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room_a = create_room(physical_capacity=12, name="Room A")
    room_b = create_room(physical_capacity=12, name="Room B")
    instructor = create_instructor(certified_level_indices=[0], buffer_minutes=15)
    create_session(program["id"], room_a["id"], instructor["id"],
                   start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    resp = api.create_session(
        f.create_session_payload(
            program["id"], room_b["id"], instructor["id"],
            start_at="2026-05-10T10:10:00Z", end_at="2026-05-10T11:00:00Z", capacity=5,
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_SCHEDULE_CONFLICT.value)


def test_instructor_buffer_allows_session_outside_buffer(api):
    """PRD §2.11: "the session's [start_at, end_at) expanded by buffer_minutes on
    each side; the expanded interval must not overlap any other non-CANCELLED
    session of the same instructor, or the new session is rejected with
    ERR_INSTRUCTOR_SCHEDULE_CONFLICT (HTTP 409)."

    Companion: a session starting 16 minutes after the prior ends clears the
    15-minute buffer and is accepted (201).

    Design: Difficulty/resource_temporal_overlap/instructor_buffer_overlap_rejects_within_buffer_gap
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room_a = create_room(physical_capacity=12, name="Room A")
    room_b = create_room(physical_capacity=12, name="Room B")
    instructor = create_instructor(certified_level_indices=[0], buffer_minutes=15)
    create_session(program["id"], room_a["id"], instructor["id"],
                   start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    resp = api.create_session(
        f.create_session_payload(
            program["id"], room_b["id"], instructor["id"],
            start_at="2026-05-10T10:16:00Z", end_at="2026-05-10T11:00:00Z", capacity=5,
        ),
        STAFF,
    )
    created = validate_success(resp, 201)
    assert created["status"] == "SCHEDULED"


def test_room_adjacency_allowed_but_strict_overlap_rejected(api):
    """PRD §2.10: "Adjacency is therefore allowed — one event's end_at equal to
    another's start_at does not overlap."
    PRD §2.10: "it must not strictly overlap any other non-CANCELLED session or any
    other non-CANCELLED BIRTHDAY_PARTY booking on the same room, and a violation is
    rejected with ERR_ROOM_SCHEDULE_CONFLICT (HTTP 409)."

    Room A hosts 09:00-10:00 and an adjacent 10:00-11:00 (accepted, SCHEDULED). A
    third strictly-overlapping 10:30-11:30 session on Room A is rejected.

    Design: Difficulty/resource_temporal_overlap/room_adjacency_allowed_but_strict_overlap_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room_a = create_room(physical_capacity=12, name="Room A")
    inst1 = create_instructor(certified_level_indices=[0], buffer_minutes=0, full_name="I1")
    inst2 = create_instructor(certified_level_indices=[0], buffer_minutes=0, full_name="I2")
    inst3 = create_instructor(certified_level_indices=[0], buffer_minutes=0, full_name="I3")
    create_session(program["id"], room_a["id"], inst1["id"],
                   start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    adj = create_session(program["id"], room_a["id"], inst2["id"],
                         start_at="2026-05-10T10:00:00Z", end_at="2026-05-10T11:00:00Z", capacity=5)
    assert adj["status"] == "SCHEDULED", "adjacency (end==start) must be allowed"
    resp = api.create_session(
        f.create_session_payload(
            program["id"], room_a["id"], inst3["id"],
            start_at="2026-05-10T10:30:00Z", end_at="2026-05-10T11:30:00Z", capacity=5,
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_SCHEDULE_CONFLICT.value)


def test_room_adjacent_session_at_prior_end_is_accepted(api):
    """PRD §2.10: "Adjacency is therefore allowed — one event's end_at equal to
    another's start_at does not overlap."

    Companion isolating the adjacency-allowed half: a second session on the same
    room whose start_at exactly equals the first's end_at is accepted as SCHEDULED
    (no conflict).

    Design: Difficulty/resource_temporal_overlap/room_adjacency_allowed_but_strict_overlap_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room_a = create_room(physical_capacity=12, name="Room A")
    inst1 = create_instructor(certified_level_indices=[0], buffer_minutes=0, full_name="I1")
    inst2 = create_instructor(certified_level_indices=[0], buffer_minutes=0, full_name="I2")
    create_session(program["id"], room_a["id"], inst1["id"],
                   start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    resp = api.create_session(
        f.create_session_payload(
            program["id"], room_a["id"], inst2["id"],
            start_at="2026-05-10T10:00:00Z", end_at="2026-05-10T11:00:00Z", capacity=5,
        ),
        STAFF,
    )
    created = validate_success(resp, 201)
    assert created["status"] == "SCHEDULED"


def test_instructor_not_certified_for_level_rejected_on_session_create(api):
    """PRD §3.3: "The instructor must be certified for the session's level: the
    program's level_index must appear in the instructor's certified_level_indices,
    or the create is rejected with ERR_INSTRUCTOR_NOT_CERTIFIED (HTTP 422)."

    Scheduling a level-1 session with an instructor certified only for [0] is
    rejected with ERR_INSTRUCTOR_NOT_CERTIFIED.

    Design: Corner/validations/instructor_not_certified_for_level_on_session_create
    """
    prog1 = create_program(level_index=1, tuition_cents=5000)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    resp = api.create_session(
        f.create_session_payload(
            prog1["id"], room["id"], instructor["id"],
            start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5,
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_CERTIFIED.value)


def test_open_gym_overlap_exceeding_room_capacity_rejected(api):
    """PRD §2.10: "OPEN_GYM bookings are shared: several may coexist in an
    overlapping window provided that the sum of head_count across all overlapping
    CONFIRMED OPEN_GYM bookings does not exceed the room's physical_capacity;
    exceeding it is the same ERR_ROOM_SCHEDULE_CONFLICT."

    Room capacity 10; one CONFIRMED OPEN_GYM head_count 8 over 09:00-11:00. A second
    overlapping OPEN_GYM head_count 5 (sum 13 > 10) is rejected.

    Design: Corner/validations/open_gym_overlap_exceeds_room_capacity_returns_conflict
    """
    room = create_room(physical_capacity=10, name="Gym")
    family = create_family()
    v0 = room["version"]
    get_success_data(api.create_facility_booking(
        f.create_facility_booking_payload(
            room["id"], family["id"], "OPEN_GYM", v0,
            start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T11:00:00Z", head_count=8,
        ),
        STAFF,
    ))
    v1 = get_success_data(api.get_room(room["id"], STAFF))["version"]
    resp = api.create_facility_booking(
        f.create_facility_booking_payload(
            room["id"], family["id"], "OPEN_GYM", v1,
            start_at="2026-05-10T10:00:00Z", end_at="2026-05-10T12:00:00Z", head_count=5,
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_SCHEDULE_CONFLICT.value)


def test_birthday_party_blocks_overlapping_session_same_room(api):
    """PRD §3.8: "A BIRTHDAY_PARTY is private and occupies the whole room
    exclusively for its interval regardless of head_count"
    PRD §3.8: "a BIRTHDAY_PARTY cannot strictly overlap any other non-CANCELLED
    session or BIRTHDAY_PARTY on that room ... either violation is
    ERR_ROOM_SCHEDULE_CONFLICT."

    A CONFIRMED BIRTHDAY_PARTY 09:00-11:00 blocks a 10:00-10:30 session on the same
    room with ERR_ROOM_SCHEDULE_CONFLICT.

    Design: Corner/validations/birthday_party_blocks_overlapping_session_same_room
    """
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=30, name="Party Room")
    instructor = create_instructor(certified_level_indices=[0], buffer_minutes=0)
    family = create_family()
    v0 = room["version"]
    get_success_data(api.create_facility_booking(
        f.create_facility_booking_payload(
            room["id"], family["id"], "BIRTHDAY_PARTY", v0,
            start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T11:00:00Z", head_count=12,
        ),
        STAFF,
    ))
    resp = api.create_session(
        f.create_session_payload(
            program["id"], room["id"], instructor["id"],
            start_at="2026-05-10T10:00:00Z", end_at="2026-05-10T10:30:00Z", capacity=5,
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_SCHEDULE_CONFLICT.value)


def test_cancel_booking_releases_room_for_later_session(api):
    """PRD §3.8: "Cancelling a booking, valid only from CONFIRMED, moves it to the
    terminal CANCELLED state, releases the room interval for later use, and
    increments the room's version."

    After cancelling a BIRTHDAY_PARTY 09:00-11:00, a 10:00-10:30 session in the
    previously-blocked window on the same room is accepted (201).

    Design: Corner/endpoints/facility_booking_cancel_releases_room_for_session
    """
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=30, name="Party Room")
    instructor = create_instructor(certified_level_indices=[0], buffer_minutes=0)
    family = create_family()
    v0 = room["version"]
    booking = get_success_data(api.create_facility_booking(
        f.create_facility_booking_payload(
            room["id"], family["id"], "BIRTHDAY_PARTY", v0,
            start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T11:00:00Z", head_count=12,
        ),
        STAFF,
    ))
    get_success_data(api.cancel_facility_booking(booking["id"], STAFF))
    resp = api.create_session(
        f.create_session_payload(
            program["id"], room["id"], instructor["id"],
            start_at="2026-05-10T10:00:00Z", end_at="2026-05-10T10:30:00Z", capacity=5,
        ),
        STAFF,
    )
    created = validate_success(resp, 201)
    assert created["status"] == "SCHEDULED"


def test_session_end_before_start_returns_invalid_request(api):
    """PRD §3.3: "the session interval start_at (inclusive) and end_at (exclusive,
    and strictly after start_at, else ERR_INVALID_REQUEST)"

    A session with end_at before start_at returns ERR_INVALID_REQUEST 400.

    Design: Corner/errors/invalid_request_end_before_start_on_session_create
    """
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    resp = api.create_session(
        f.create_session_payload(
            program["id"], room["id"], instructor["id"],
            start_at="2026-05-10T10:00:00Z", end_at="2026-05-10T09:00:00Z", capacity=5,
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_session_capacity_exceeding_room_capacity_returns_invalid_request(api):
    """PRD §3.3: "capacity must be at least 1 and must not exceed the chosen room's
    physical_capacity; a capacity larger than the room is a malformed request,
    ERR_INVALID_REQUEST."

    A session capacity 10 against a room of physical_capacity 4 returns
    ERR_INVALID_REQUEST 400.

    Design: Corner/entities/session_capacity_exceeds_room_physical_capacity_invalid_request
    """
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=4, name="Small")
    instructor = create_instructor(certified_level_indices=[0])
    resp = api.create_session(
        f.create_session_payload(
            program["id"], room["id"], instructor["id"],
            start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=10,
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
