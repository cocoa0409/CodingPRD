"""Optimistic concurrency (stale session/room version) and the hold precondition
that an INACTIVE instructor blocks holding a session.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_program, create_room, create_instructor, create_session,
    create_active_membership, create_family, create_child, enroll_child,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["studio_admin_headers"]
STAFF = TEST_USERS["front_desk_headers"]


def test_hold_with_inactive_instructor_returns_not_certified(api):
    """PRD §3.3: "the assigned instructor's status must be ACTIVE at hold time (an
    INACTIVE instructor blocks the hold with ERR_INSTRUCTOR_NOT_CERTIFIED)"

    A SCHEDULED session whose instructor is deactivated before the hold (clock at or
    after start) is blocked with ERR_INSTRUCTOR_NOT_CERTIFIED.

    Design: Difficulty/cross_entity_state_dependency/hold_blocked_when_instructor_inactive_pair_session_instructor
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    get_success_data(api.deactivate_instructor(instructor["id"], ADMIN))
    set_clock("2026-05-10T09:30:00Z")
    resp = api.hold_session(session["id"], {"attendance": []}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_CERTIFIED.value)


def test_hold_with_active_instructor_after_start_succeeds(api):
    """PRD §3.3: "Holding a session, valid only from SCHEDULED, advances it to HELD."
    PRD §3.3: "the assigned instructor's status must be ACTIVE at hold time"

    Companion: a SCHEDULED session with an ACTIVE instructor and the clock at/after
    start_at holds successfully to HELD.

    Design: Difficulty/cross_entity_state_dependency/hold_blocked_when_instructor_inactive_pair_session_instructor
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    set_clock("2026-05-10T09:30:00Z")
    held = validate_success(api.hold_session(session["id"], {"attendance": []}, STAFF), 200)
    assert held["status"] == "HELD"


def test_enroll_with_stale_session_version_returns_412(api):
    """PRD §2.8: "The create request must carry expected_session_version, the
    version of the target ClassSession the client last observed. If that value does
    not equal the session's current version, the create is rejected with
    ERR_STALE_VERSION (HTTP 412)."

    After one enroll bumps the session version, a second enroll carrying the stale
    pre-bump version is rejected with ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_session_version_on_enroll_returns_412
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    v0 = session["version"]
    family, membership = create_active_membership(tier="PLUS")
    child_a = create_child(family["id"], full_name="A", birth_date="2024-01-01")
    child_b = create_child(family["id"], full_name="B", birth_date="2024-02-01")
    enroll_child(child_a["id"], session["id"], membership["id"], kind="RECURRING",
                 expected_session_version=v0)  # bumps version off v0
    resp = api.create_enrollment(
        f.create_enrollment_payload(child_b["id"], session["id"], membership["id"], v0, kind="RECURRING"),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_book_with_stale_room_version_returns_412(api):
    """PRD §2.8: "The booking request must carry expected_room_version, the version
    of the target Room the client last observed. If that value does not equal the
    room's current version, the booking is rejected with ERR_STALE_VERSION (HTTP 412)."

    After one booking bumps the room version, a second booking carrying the stale
    pre-bump version is rejected with ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_room_version_on_booking_returns_412
    """
    room = create_room(physical_capacity=20, name="Gym")
    v0 = room["version"]
    family = create_family()
    get_success_data(api.create_facility_booking(
        f.create_facility_booking_payload(
            room["id"], family["id"], "OPEN_GYM", v0,
            start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", head_count=3,
        ),
        STAFF,
    ))  # bumps room version off v0
    resp = api.create_facility_booking(
        f.create_facility_booking_payload(
            room["id"], family["id"], "OPEN_GYM", v0,
            start_at="2026-05-10T11:00:00Z", end_at="2026-05-10T12:00:00Z", head_count=3,
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
