"""Temporal-overlap rules and deadline-instant boundaries: half-open session
overlap (with adjacency allowed), the closed buffered showcase-session clash,
the inclusive entry-deadline instant, and the close-entries deadline precondition.

Covers difficulty rules resource_temporal_overlap and the showcase-deadline
boundary_precision_check instance, plus the corner close-entries-before-deadline
instance.
"""
import pytest
from test_helpers import (
    get_success_data, validate_success, validate_error,
    create_enrollment_payload, create_showcase_entry_payload,
    setup_catalogue, create_guardian, create_member, create_open_session,
    enroll_drop_in, current_session_version, set_clock, submit_entry,
    make_guardian_headers, TEST_USERS,
    api_client,
)

ADMIN = TEST_USERS["center_admin_headers"]


# ─── resource_temporal_overlap / member_schedule_half_open_session_overlap ─
def test_overlapping_session_enrollment_rejected(api):
    """PRD §3.5: "the target session's half-open time interval, from its `starts_at`
    inclusive to its `ends_at` exclusive, must not overlap the half-open interval of any
    other session in which this member holds a non-terminal enrollment (`RESERVED` or
    `CHECKED_IN`)"
    PRD §3.5: "An overlap is rejected with `ERR_MEMBER_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/member_schedule_half_open_session_overlap
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=1000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    sess_a, _ = create_open_session(center["id"], program["id"],
                                    starts_at="2026-05-01T16:00:00Z",
                                    ends_at="2026-05-01T18:00:00Z", assigned_instructor_count=5)
    sess_b, vb = create_open_session(center["id"], program["id"],
                                     starts_at="2026-05-01T17:00:00Z",
                                     ends_at="2026-05-01T19:00:00Z", assigned_instructor_count=5)
    enroll_drop_in(guardian["id"], sess_a["id"], member["id"], sibling_index=1)
    res = api.create_enrollment(
        create_enrollment_payload(sess_b["id"], member["id"], vb, coverage="DROP_IN",
                                 sibling_index=1),
        make_guardian_headers(guardian["id"]),
    )
    validate_error(res, "ERR_MEMBER_SCHEDULE_CONFLICT")


def test_adjacent_session_enrollment_allowed(api):
    """PRD §3.5: "adjacency is allowed, so two sessions where one's `ends_at` equals the
    other's `starts_at` do not conflict because the interval is end-exclusive."

    Design: Difficulty/resource_temporal_overlap/member_schedule_half_open_session_overlap
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=1000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    sess_a, _ = create_open_session(center["id"], program["id"],
                                    starts_at="2026-05-01T16:00:00Z",
                                    ends_at="2026-05-01T18:00:00Z", assigned_instructor_count=5)
    sess_c, vc = create_open_session(center["id"], program["id"],
                                     starts_at="2026-05-01T18:00:00Z",
                                     ends_at="2026-05-01T20:00:00Z", assigned_instructor_count=5)
    enroll_drop_in(guardian["id"], sess_a["id"], member["id"], sibling_index=1)
    res = api.create_enrollment(
        create_enrollment_payload(sess_c["id"], member["id"], vc, coverage="DROP_IN",
                                 sibling_index=1),
        make_guardian_headers(guardian["id"]),
    )
    entry = validate_success(res, 201)
    assert entry["attendance_status"] == "RESERVED"


# ─── resource_temporal_overlap / showcase_buffered_closed_window_vs_session_start ─
def test_showcase_session_clash_within_buffer_rejected(api):
    """PRD §3.8: "the symmetric closed window spanning 120 minutes before to 120 minutes
    after the showcase's `starts_at` must not contain the `starts_at` of any session in
    which the member holds a non-terminal enrollment"
    PRD §3.8: "a violation is rejected with `ERR_SHOWCASE_SESSION_CLASH` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/showcase_buffered_closed_window_vs_session_start
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=1000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    # Session starts 2026-05-11T10:00:00Z; showcase starts 11:00:00Z (60m < 120m buffer).
    session, _ = create_open_session(center["id"], program["id"],
                                     starts_at="2026-05-11T10:00:00Z",
                                     ends_at="2026-05-11T12:00:00Z", assigned_instructor_count=5)
    enroll_drop_in(guardian["id"], session["id"], member["id"], sibling_index=1)
    created = get_success_data(api.create_showcase(
        {"center_id": center["id"], "program_id": program["id"], "min_belt_rank": 1,
         "capacity": 10, "starts_at": "2026-05-11T11:00:00Z",
         "entry_deadline_at": "2026-05-10T11:00:00Z"}, ADMIN))
    get_success_data(api.open_showcase(created["id"], ADMIN))
    set_clock("2026-05-09T00:00:00Z")  # before the deadline so only the clash can fire
    res = api.create_showcase_entry(
        create_showcase_entry_payload(created["id"], member["id"]),
        make_guardian_headers(guardian["id"]),
    )
    validate_error(res, "ERR_SHOWCASE_SESSION_CLASH")


def test_showcase_session_clash_status_409(api):
    """PRD §3.8: "unlike the half-open member-schedule rule for sessions, this clash is
    evaluated as a closed buffered window around the single showcase-start instant, and a
    violation is rejected with `ERR_SHOWCASE_SESSION_CLASH` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/showcase_buffered_closed_window_vs_session_start
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=1000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"],
                                     starts_at="2026-05-11T10:00:00Z",
                                     ends_at="2026-05-11T12:00:00Z", assigned_instructor_count=5)
    enroll_drop_in(guardian["id"], session["id"], member["id"], sibling_index=1)
    created = get_success_data(api.create_showcase(
        {"center_id": center["id"], "program_id": program["id"], "min_belt_rank": 1,
         "capacity": 10, "starts_at": "2026-05-11T11:00:00Z",
         "entry_deadline_at": "2026-05-10T11:00:00Z"}, ADMIN))
    get_success_data(api.open_showcase(created["id"], ADMIN))
    set_clock("2026-05-09T00:00:00Z")
    res = api.create_showcase_entry(
        create_showcase_entry_payload(created["id"], member["id"]),
        make_guardian_headers(guardian["id"]),
    )
    assert res.status_code == 409


# ─── boundary_precision_check / showcase_entry_deadline_inclusive_instant_boundary ─
def test_entry_at_deadline_instant_accepted(api):
    """PRD §3.8: "The entry must be submitted at or before the showcase's
    `entry_deadline_at` (the boundary instant is inclusive); after that instant the request
    is rejected with `ERR_ENTRY_DEADLINE_PASSED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/showcase_entry_deadline_inclusive_instant_boundary
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    created = get_success_data(api.create_showcase(
        {"center_id": center["id"], "program_id": program["id"], "min_belt_rank": 1,
         "capacity": 10, "starts_at": "2026-05-11T09:00:00Z",
         "entry_deadline_at": "2026-05-10T12:00:00Z"}, ADMIN))
    get_success_data(api.open_showcase(created["id"], ADMIN))
    set_clock("2026-05-10T12:00:00Z")  # exactly at the deadline (inclusive)
    res = api.create_showcase_entry(
        create_showcase_entry_payload(created["id"], member["id"]),
        make_guardian_headers(guardian["id"]),
    )
    entry = validate_success(res, 201)
    assert entry["status"] == "SUBMITTED"


def test_entry_one_second_past_deadline_rejected(api):
    """PRD §3.8: "after that instant the request is rejected with
    `ERR_ENTRY_DEADLINE_PASSED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/showcase_entry_deadline_inclusive_instant_boundary
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    created = get_success_data(api.create_showcase(
        {"center_id": center["id"], "program_id": program["id"], "min_belt_rank": 1,
         "capacity": 10, "starts_at": "2026-05-11T09:00:00Z",
         "entry_deadline_at": "2026-05-10T12:00:00Z"}, ADMIN))
    get_success_data(api.open_showcase(created["id"], ADMIN))
    set_clock("2026-05-10T12:00:01Z")  # one second after the inclusive deadline
    res = api.create_showcase_entry(
        create_showcase_entry_payload(created["id"], member["id"]),
        make_guardian_headers(guardian["id"]),
    )
    validate_error(res, "ERR_ENTRY_DEADLINE_PASSED")


# ─── Corner / state_machines / close_entries_before_deadline_returns_error ─
def test_close_entries_before_deadline_rejected(api):
    """PRD §3.8: "this is permitted only from `OPEN` and only when the logical clock's
    "now" is strictly after the `entry_deadline_at` (otherwise it is rejected with
    `ERR_DEADLINE_NOT_REACHED`, HTTP 409)."

    Design: Corner/state_machines/close_entries_before_deadline_returns_error
    """
    center = get_success_data(api.create_center(
        {"name": "C1", "device_count": 20, "min_student_instructor_ratio": 6}, ADMIN))
    program = get_success_data(api.create_program(
        {"name": "P", "code": "CDD1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 4000},
        ADMIN))
    created = get_success_data(api.create_showcase(
        {"center_id": center["id"], "program_id": program["id"], "min_belt_rank": 1,
         "capacity": 5, "starts_at": "2026-05-11T09:00:00Z",
         "entry_deadline_at": "2026-05-10T12:00:00Z"}, ADMIN))
    get_success_data(api.open_showcase(created["id"], ADMIN))
    # Clock at default 2026-04-01 => before the deadline.
    res = api.close_showcase_entries(created["id"], ADMIN)
    validate_error(res, "ERR_DEADLINE_NOT_REACHED")
