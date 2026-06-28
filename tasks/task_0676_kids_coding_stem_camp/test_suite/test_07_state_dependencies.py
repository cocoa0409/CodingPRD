"""Cross-entity state dependencies and invalid-transition lockdown.

Covers difficulty rule cross_entity_state_dependency (entry accept depends on
showcase OPEN; check-in depends on session reaching starts_at) and corner
state-machine instances for double-open, complete-before-end, and terminal
lockdown.
"""
import pytest
from test_helpers import (
    get_success_data, validate_error,
    create_accept_payload,
    setup_catalogue, create_guardian, create_member, create_open_session,
    enroll_drop_in, set_clock, submit_entry,
    make_guardian_headers, TEST_USERS,
    api_client,
)

ADMIN = TEST_USERS["center_admin_headers"]
INSTRUCTOR = TEST_USERS["instructor_headers"]


# ─── cross_entity_state_dependency / entry_accept_requires_showcase_open_entry_to_showcase ─
def test_accept_after_close_entries_rejected_invalid_state(api):
    """PRD §3.8: "acceptance requires that the entry is `SUBMITTED`, the showcase is
    `OPEN`, the showcase's `accepted_entry_count` is below its `capacity`, and the member's
    current belt rank meets or exceeds the showcase's `min_belt_rank`."
    PRD §3.8: "Closing entries sweeps every entry still in `SUBMITTED` to `REJECTED`"

    Design: Difficulty/cross_entity_state_dependency/entry_accept_requires_showcase_open_entry_to_showcase
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    created = get_success_data(api.create_showcase(
        {"center_id": center["id"], "program_id": program["id"], "min_belt_rank": 1,
         "capacity": 10, "starts_at": "2026-05-11T09:00:00Z",
         "entry_deadline_at": "2026-05-10T12:00:00Z"}, ADMIN))
    opened = get_success_data(api.open_showcase(created["id"], ADMIN))
    entry = submit_entry(guardian["id"], opened["id"], member["id"])
    set_clock("2026-05-10T12:00:01Z")
    judging = get_success_data(api.close_showcase_entries(created["id"], ADMIN))
    # The SUBMITTED entry was swept to REJECTED and showcase is JUDGING; accept must fail.
    res = api.accept_showcase_entry(entry["id"], create_accept_payload(judging["version"]), ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


def test_entry_swept_to_rejected_on_close(api):
    """PRD §3.8: "Closing entries sweeps every entry still in `SUBMITTED` to `REJECTED`
    and increments the showcase's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/entry_accept_requires_showcase_open_entry_to_showcase
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    created = get_success_data(api.create_showcase(
        {"center_id": center["id"], "program_id": program["id"], "min_belt_rank": 1,
         "capacity": 10, "starts_at": "2026-05-11T09:00:00Z",
         "entry_deadline_at": "2026-05-10T12:00:00Z"}, ADMIN))
    opened = get_success_data(api.open_showcase(created["id"], ADMIN))
    entry = submit_entry(guardian["id"], opened["id"], member["id"])
    set_clock("2026-05-10T12:00:01Z")
    api.close_showcase_entries(created["id"], ADMIN)
    entry_after = get_success_data(api.get_showcase_entry(entry["id"], ADMIN))
    assert entry_after["status"] == "REJECTED"


# ─── cross_entity_state_dependency / checkin_requires_session_started_enrollment_to_session ─
def test_checkin_before_session_start_rejected(api):
    """PRD §3.5: "Check-in is permitted only when the enrollment's attendance is
    `RESERVED`, the session's status is one of `OPEN`, `RESTRICTED`, or `FULL`, and the
    logical clock's "now" is at or after the session's `starts_at`."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_session_started_enrollment_to_session
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    # Clock left at default 2026-04-01, before starts_at 2026-05-01T16:00:00Z.
    res = api.check_in_enrollment(enrollment["id"], INSTRUCTOR)
    validate_error(res, "ERR_INVALID_STATE")


def test_checkin_before_start_leaves_attendance_reserved(api):
    """PRD §3.5: "Check-in is permitted only when the enrollment's attendance is
    `RESERVED`, the session's status is one of `OPEN`, `RESTRICTED`, or `FULL`, and the
    logical clock's "now" is at or after the session's `starts_at`."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_session_started_enrollment_to_session
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    api.check_in_enrollment(enrollment["id"], INSTRUCTOR)  # rejected, no state change
    after = get_success_data(api.get_enrollment(enrollment["id"], ADMIN))
    assert after["attendance_status"] == "RESERVED"


# ─── Corner / state_machines / open_already_open_session_returns_invalid_state ─
def test_open_already_open_session_rejected(api):
    """PRD §3.4: "It is permitted only when the session is currently `DRAFT`, the
    `ends_at` is strictly after the `starts_at`, and the `assigned_instructor_count` is at
    least 1."
    PRD §3.3: "Any state-transition action attempted from a state in which it is not
    defined is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/open_already_open_session_returns_invalid_state
    """
    center = get_success_data(api.create_center(
        {"name": "C1", "device_count": 20, "min_student_instructor_ratio": 6}, ADMIN))
    program = get_success_data(api.create_program(
        {"name": "P", "code": "OAO1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 4000},
        ADMIN))
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=2)
    res = api.open_session(session["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner / state_machines / complete_session_before_end_returns_session_not_ended ─
def test_complete_session_before_end_rejected(api):
    """PRD §3.4: "If completion is attempted before the clock reaches `ends_at`, it is
    rejected with `ERR_SESSION_NOT_ENDED` (HTTP 409)."

    Design: Corner/state_machines/complete_session_before_end_returns_session_not_ended
    """
    center = get_success_data(api.create_center(
        {"name": "C1", "device_count": 20, "min_student_instructor_ratio": 6}, ADMIN))
    program = get_success_data(api.create_program(
        {"name": "P", "code": "CSB1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 4000},
        ADMIN))
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=2)
    # Clock at default 2026-04-01, before ends_at 2026-05-01T18:00:00Z.
    res = api.complete_session(session["id"], ADMIN)
    validate_error(res, "ERR_SESSION_NOT_ENDED")


# ─── Corner / state_machines / terminal_cancelled_session_cannot_complete ─
def test_terminal_cancelled_session_cannot_complete(api):
    """PRD §3.4: "Completing a session transitions it from `OPEN`, `RESTRICTED`, or `FULL`
    to `COMPLETED`, and is restricted to a `CenterAdmin`; it is permitted only when the
    session's status is one of `OPEN`, `RESTRICTED`, or `FULL`, and only when the logical
    clock's "now" is at or after the session's `ends_at`."

    Design: Corner/state_machines/terminal_cancelled_session_cannot_complete
    """
    center = get_success_data(api.create_center(
        {"name": "C1", "device_count": 20, "min_student_instructor_ratio": 6}, ADMIN))
    program = get_success_data(api.create_program(
        {"name": "P", "code": "TCS1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 4000},
        ADMIN))
    session = get_success_data(api.create_session(
        {"center_id": center["id"], "program_id": program["id"], "format": "AFTER_SCHOOL",
         "week_count": 1, "starts_at": "2026-05-01T16:00:00Z", "ends_at": "2026-05-01T18:00:00Z",
         "device_seats_requested": 1, "assigned_instructor_count": 2}, ADMIN))
    get_success_data(api.cancel_session(session["id"], ADMIN))  # DRAFT -> CANCELLED (terminal)
    res = api.complete_session(session["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")
