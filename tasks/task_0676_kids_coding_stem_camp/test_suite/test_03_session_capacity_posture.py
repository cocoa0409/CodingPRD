"""Session effective capacity, the exact seat boundary, and posture derivation
(OPEN / RESTRICTED / FULL) including the empty-restricted-band edge.

Covers difficulty rule boundary_precision_check (seat boundary) plus corner
state-machine instances for posture thresholds and FULL->OPEN reversion.
"""
import pytest
from test_helpers import (
    get_success_data, validate_error,
    setup_catalogue, create_guardian, create_member, create_open_session,
    enroll_drop_in, current_session_version,
    create_enrollment_payload,
    make_guardian_headers, TEST_USERS,
    api_client,
)

ADMIN = TEST_USERS["center_admin_headers"]


# ─── boundary_precision_check / session_capacity_exact_seat_boundary_on_enrollment ─
def test_enrollment_at_exact_capacity_marks_session_full(api):
    """PRD §2.6: "When the confirmed seat count equals the effective capacity exactly,
    the posture is `FULL`."

    Design: Difficulty/boundary_precision_check/session_capacity_exact_seat_boundary_on_enrollment
    """
    center = get_success_data(api.create_center(
        {"name": "C1", "device_count": 2, "min_student_instructor_ratio": 2}, ADMIN))
    program = get_success_data(api.create_program(
        {"name": "P", "code": "CAP1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 1000},
        ADMIN))
    get_success_data(api.create_belt_level(
        {"program_id": program["id"], "name": "White", "rank": 1, "required_badge_count": 0},
        ADMIN))
    guardian = create_guardian()
    m1 = create_member(guardian["id"], program["id"])
    m2 = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"],
                                     device_seats_requested=1, assigned_instructor_count=1)
    # effective_capacity = min(2//1, 1*2) = 2.
    enroll_drop_in(guardian["id"], session["id"], m1["id"], sibling_index=1)
    enroll_drop_in(guardian["id"], session["id"], m2["id"], sibling_index=2)
    after = get_success_data(api.get_session(session["id"], ADMIN))
    assert after["confirmed_seat_count"] == 2
    assert after["status"] == "FULL"


def test_enrollment_above_capacity_rejected(api):
    """PRD §3.5: "The enrollment must not push the session's `confirmed_seat_count` above
    the session's effective capacity; a create that would exceed effective capacity is
    rejected with `ERR_SESSION_AT_CAPACITY` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/session_capacity_exact_seat_boundary_on_enrollment
    """
    center = get_success_data(api.create_center(
        {"name": "C1", "device_count": 2, "min_student_instructor_ratio": 2}, ADMIN))
    program = get_success_data(api.create_program(
        {"name": "P", "code": "CAP2", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 1000},
        ADMIN))
    get_success_data(api.create_belt_level(
        {"program_id": program["id"], "name": "White", "rank": 1, "required_badge_count": 0},
        ADMIN))
    guardian = create_guardian()
    m1 = create_member(guardian["id"], program["id"])
    m2 = create_member(guardian["id"], program["id"])
    m3 = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"],
                                     device_seats_requested=1, assigned_instructor_count=1)
    enroll_drop_in(guardian["id"], session["id"], m1["id"], sibling_index=1)
    enroll_drop_in(guardian["id"], session["id"], m2["id"], sibling_index=2)
    v2 = current_session_version(session["id"])
    res = api.create_enrollment(
        create_enrollment_payload(session["id"], m3["id"], v2, coverage="DROP_IN",
                                 sibling_index=3),
        make_guardian_headers(guardian["id"]),
    )
    validate_error(res, "ERR_SESSION_AT_CAPACITY")


# ─── Corner / state_machines / session_posture_restricted_at_80_percent_threshold ─
def test_session_posture_flips_to_restricted_at_threshold(api):
    """PRD §2.6: "When the confirmed seat count is at least the rounded-up restricted
    threshold but still strictly below the effective capacity, the posture is `RESTRICTED`."

    Design: Corner/state_machines/session_posture_restricted_at_80_percent_threshold
    """
    center = get_success_data(api.create_center(
        {"name": "C1", "device_count": 5, "min_student_instructor_ratio": 5}, ADMIN))
    program = get_success_data(api.create_program(
        {"name": "P", "code": "POS1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 1000},
        ADMIN))
    get_success_data(api.create_belt_level(
        {"program_id": program["id"], "name": "White", "rank": 1, "required_badge_count": 0},
        ADMIN))
    guardian = create_guardian()
    members = [create_member(guardian["id"], program["id"]) for _ in range(4)]
    session, _ = create_open_session(center["id"], program["id"],
                                     device_seats_requested=1, assigned_instructor_count=1)
    # effective_capacity = min(5//1, 1*5) = 5; restricted threshold = ceil(0.8*5) = 4.
    for i, m in enumerate(members, start=1):
        enroll_drop_in(guardian["id"], session["id"], m["id"], sibling_index=i)
    after = get_success_data(api.get_session(session["id"], ADMIN))
    assert after["confirmed_seat_count"] == 4
    assert after["status"] == "RESTRICTED"


# ─── Corner / state_machines / session_full_reverts_to_open_on_cancel_empty_restricted_band ─
def test_full_session_reverts_to_open_on_cancel_empty_restricted_band(api):
    """PRD §3.4: "or directly from `FULL` to `OPEN` (when the post-cancel count falls
    below the rounded-up restricted threshold, which happens for small capacities whose
    restricted band is empty)."

    Design: Corner/state_machines/session_full_reverts_to_open_on_cancel_empty_restricted_band
    """
    center = get_success_data(api.create_center(
        {"name": "C1", "device_count": 2, "min_student_instructor_ratio": 2}, ADMIN))
    program = get_success_data(api.create_program(
        {"name": "P", "code": "FR1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 1000},
        ADMIN))
    get_success_data(api.create_belt_level(
        {"program_id": program["id"], "name": "White", "rank": 1, "required_badge_count": 0},
        ADMIN))
    guardian = create_guardian()
    m1 = create_member(guardian["id"], program["id"])
    m2 = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"],
                                     device_seats_requested=1, assigned_instructor_count=1)
    e1 = enroll_drop_in(guardian["id"], session["id"], m1["id"], sibling_index=1)
    enroll_drop_in(guardian["id"], session["id"], m2["id"], sibling_index=2)
    # Session now FULL (cap 2). Cancel one >=24h before start (clock default).
    get_success_data(api.cancel_enrollment(e1["id"], make_guardian_headers(guardian["id"])))
    after = get_success_data(api.get_session(session["id"], ADMIN))
    assert after["confirmed_seat_count"] == 1
    assert after["status"] == "OPEN"
