"""Perpetual enrollment: the ACTIVE<->PAUSED cycle, capacity boundary and
waitlisting, seat conservation through withdraw+promotion, cross-entity state
preconditions, and immediate count consistency.

Difficulty queue (A): non_linear_state_machine (Enrollment), boundary_precision
(capacity), compensating_invariant (seats), cross_entity_state_dependency
(enrollment->session).
Corner queue (B): state_machines + consistency_model enrollment instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_parent_headers,
    set_clock,
    create_location,
    create_level,
    create_instructor,
    create_class_session,
    open_session,
    create_parent,
    create_student,
    setup_parent_with_student,
    setup_open_session,
    setup_single_active_enrollment,
    create_active_enrollment,
    create_enrollment_with_version,
    create_enrollment_payload,
    pause_enrollment,
    setup_capacity1_with_waitlist,
    get_session_version,
)

ADMIN = TEST_USERS["school_admin_headers"]


# ─── non_linear_state_machine: ACTIVE -> PAUSED -> ACTIVE cycle ────────────
def test_enrollment_pause_then_resume_returns_to_active(api):
    """PRD §3.6: "Resuming reverses the pause: a `Parent` or `SchoolAdmin` moves
    an enrollment from `PAUSED` back to `ACTIVE`, after ownership is confirmed,
    the child's age is re-checked against the level window"

    Pause then resume returns the same enrollment row to ACTIVE — a cycle, not a
    forward-only pipeline.

    Design: Difficulty/non_linear_state_machine/enrollment_active_pause_resume_cycle
    """
    env = setup_single_active_enrollment()
    parent = env["parent"]
    headers = make_parent_headers(parent["id"])
    pause_enrollment(parent, env["enrollment"]["id"])
    res = api.resume_enrollment(env["enrollment"]["id"], headers)
    resumed = validate_success(res, 200)
    assert resumed["status"] == "ACTIVE"


def test_enrollment_resume_reincrements_enrolled_count(api):
    """PRD §3.6: "Pausing decrements the session's `enrolled_count`"
    PRD §3.6: "A successful resume re-increments `enrolled_count` and increments
    the session's `version` by one."

    After pause (count 0) and resume the session's enrolled_count is back to 1.

    Design: Difficulty/non_linear_state_machine/enrollment_active_pause_resume_cycle
    """
    env = setup_single_active_enrollment()
    parent = env["parent"]
    headers = make_parent_headers(parent["id"])
    pause_enrollment(parent, env["enrollment"]["id"])
    validate_success(api.resume_enrollment(env["enrollment"]["id"], headers), 200)
    session = validate_success(api.get_class_session(env["session"]["id"], ADMIN), 200)
    assert session["enrolled_count"] == 1, (
        f"enrolled_count must return to 1 after resume, got {session['enrolled_count']}"
    )


# ─── boundary_precision: capacity fill then waitlist ───────────────────────
def test_first_enrollment_fills_last_seat_active(api):
    """PRD §3.6: "If there is a free seat (the session's `enrolled_count` is
    below its `capacity`) and the account is current, the enrollment becomes
    `ACTIVE`"

    Into a capacity-1 OPEN session at enrolled_count 0, the first enrollment
    activates (fills the seat to capacity).

    Design: Difficulty/boundary_precision_check/capacity_boundary_active_fills_then_waitlists
    """
    env = setup_open_session(level_overrides={
        "name": "Solo", "max_students_per_instructor": 1,
        "min_age_months": 36, "max_age_months": 200,
    })
    parent, student = setup_parent_with_student(env["level"]["id"])
    enr = create_active_enrollment(parent, student, env["session"])
    assert enr["status"] == "ACTIVE"
    session = validate_success(api.get_class_session(env["session"]["id"], ADMIN), 200)
    assert session["enrolled_count"] == 1


def test_enrollment_at_capacity_lands_waitlisted(api):
    """PRD §3.6: "If no seat is free, the enrollment is recorded as `WAITLISTED`
    instead and the session's `waitlist_count` rises."

    With the capacity-1 seat already held (enrolled_count == capacity), the next
    enrollment lands WAITLISTED and waitlist_count rises to 1.

    Design: Difficulty/boundary_precision_check/capacity_boundary_active_fills_then_waitlists
    """
    env = setup_capacity1_with_waitlist()
    assert env["enr1"]["status"] == "ACTIVE"
    assert env["enr2"]["status"] == "WAITLISTED"
    session = validate_success(api.get_class_session(env["session"]["id"], ADMIN), 200)
    assert session["enrolled_count"] == 1
    assert session["waitlist_count"] == 1


# ─── compensating_invariant: seat conservation across withdraw+promotion ───
def test_withdraw_active_promotes_waitlisted(api):
    """PRD §3.6: "If the enrollment had been `ACTIVE`, its `enrolled_count` is
    decremented and the freed seat promotes the earliest waitlisted enrollment of
    that session to `ACTIVE`"

    Withdrawing the only ACTIVE enrollment of a capacity-1 session promotes the
    waitlisted enrollment behind it to ACTIVE.

    Design: Difficulty/compensating_invariant/seat_count_conserved_after_withdraw_and_promotion
    """
    env = setup_capacity1_with_waitlist()
    headers = make_parent_headers(env["p1"]["id"])
    validate_success(api.withdraw_enrollment(env["enr1"]["id"], headers), 200)
    enr1 = validate_success(api.get_enrollment(env["enr1"]["id"], ADMIN), 200)
    enr2 = validate_success(api.get_enrollment(env["enr2"]["id"], ADMIN), 200)
    assert enr1["status"] == "WITHDRAWN"
    assert enr2["status"] == "ACTIVE", "the waitlisted enrollment must be promoted"


def test_seat_count_conserved_after_withdraw_and_promotion(api):
    """PRD §2.5: "the governing principle here is that no count or balance is
    left stale after a cascade settles."

    After the withdraw frees the last seat and the promotion fills it, the
    capacity-1 session settles at enrolled_count 1 and waitlist_count 0 — zero
    drift.

    Design: Difficulty/compensating_invariant/seat_count_conserved_after_withdraw_and_promotion
    """
    env = setup_capacity1_with_waitlist()
    headers = make_parent_headers(env["p1"]["id"])
    validate_success(api.withdraw_enrollment(env["enr1"]["id"], headers), 200)
    session = validate_success(api.get_class_session(env["session"]["id"], ADMIN), 200)
    assert session["enrolled_count"] == 1, (
        f"enrolled_count must conserve to 1, got {session['enrolled_count']}"
    )
    assert session["waitlist_count"] == 0, (
        f"waitlist_count must settle to 0, got {session['waitlist_count']}"
    )


# ─── cross_entity_state_dependency: enrollment requires OPEN session ───────
def test_enroll_into_draft_session_rejected(api):
    """PRD §3.6: "The session must be `OPEN`; attempting to enroll against a
    session that is not open is rejected with `ERR_SESSION_NOT_OPEN`."

    Creating an enrollment against a DRAFT (never-opened) session is rejected
    ERR_SESSION_NOT_OPEN.

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_session_open
    """
    set_clock("2026-01-05T00:00:00Z")
    location = create_location()
    level = create_level(min_age_months=36, max_age_months=200,
                         max_students_per_instructor=4)
    instructor = create_instructor(certified_level_ids=[level["id"]])
    session = create_class_session(location["id"], level["id"], instructor["id"])
    parent, student = setup_parent_with_student(level["id"])
    headers = make_parent_headers(parent["id"])
    res = api.create_enrollment(
        create_enrollment_payload(student["id"], session["id"], session["version"]),
        headers,
    )
    validate_error(res, "ERR_SESSION_NOT_OPEN")


def test_enroll_into_open_session_succeeds(api):
    """PRD §3.4: "Opening a session has the single forward effect of permitting
    enrollment creation against it."

    The same student/session as the DRAFT-rejection case, but once OPENED, the
    enrollment is created — confirming the OPEN state is what gates creation.

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_session_open
    """
    env = setup_open_session(level_overrides={
        "min_age_months": 36, "max_age_months": 200,
        "max_students_per_instructor": 4,
    })
    parent, student = setup_parent_with_student(env["level"]["id"])
    enr = create_active_enrollment(parent, student, env["session"])
    assert enr["status"] == "ACTIVE"


# ─── Corner queue (B): enrollment initial state + invalid transitions ──────
def test_enrollment_initial_state_active_when_seat_free(api):
    """PRD §3.6: "the enrollment becomes `ACTIVE`: its `enrolled_count` rises"

    A new enrollment into an OPEN session with a free seat and a CURRENT account
    is created directly ACTIVE with enrolled_count incremented to 1.

    Design: Corner/state_machines/enrollment_initial_state_active_when_seat_free
    """
    env = setup_open_session(level_overrides={
        "min_age_months": 0, "max_age_months": 200,
        "max_students_per_instructor": 4,
    })
    parent, student = setup_parent_with_student(env["level"]["id"])
    enr = create_active_enrollment(parent, student, env["session"])
    assert enr["status"] == "ACTIVE"
    session = validate_success(api.get_class_session(env["session"]["id"], ADMIN), 200)
    assert session["enrolled_count"] == 1


def test_pause_waitlisted_enrollment_rejected(api):
    """PRD §2.10: "an action attempted from a status the transition cannot
    legally start from is rejected with `ERR_INVALID_STATE` (HTTP 409)"

    Pausing a WAITLISTED enrollment (pause is legal only from ACTIVE) is rejected
    ERR_INVALID_STATE.

    Design: Corner/state_machines/pause_waitlisted_enrollment_returns_invalid_state
    """
    env = setup_capacity1_with_waitlist()
    headers = make_parent_headers(env["p2"]["id"])
    assert env["enr2"]["status"] == "WAITLISTED"
    res = api.pause_enrollment(env["enr2"]["id"], headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_withdrawn_enrollment_is_terminal(api):
    """PRD §3.6: "`WITHDRAWN` is terminal."

    Pausing a WITHDRAWN enrollment (no transition leaves the terminal state) is
    rejected ERR_INVALID_STATE.

    Design: Corner/state_machines/withdrawn_enrollment_is_terminal
    """
    env = setup_single_active_enrollment()
    parent = env["parent"]
    headers = make_parent_headers(parent["id"])
    validate_success(api.withdraw_enrollment(env["enrollment"]["id"], headers), 200)
    res = api.pause_enrollment(env["enrollment"]["id"], headers)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner queue (B): immediate consistency ───────────────────────────────
def test_enrolled_count_reflected_immediately(api):
    """PRD §2.5: "After any enrollment lifecycle change, a class session's
    `enrolled_count` is recomputed as the number of that session's enrollments in
    `ACTIVE` status"

    A GET on the session right after an ACTIVE enrollment create shows
    enrolled_count == 1 with no settle delay.

    Design: Corner/consistency_model/enrollment_create_reflects_count_in_same_response_cycle
    """
    env = setup_open_session(level_overrides={
        "min_age_months": 0, "max_age_months": 200,
        "max_students_per_instructor": 4,
    })
    parent, student = setup_parent_with_student(env["level"]["id"])
    enr = create_active_enrollment(parent, student, env["session"])
    session = validate_success(api.get_class_session(env["session"]["id"], ADMIN), 200)
    assert session["enrolled_count"] == 1
    assert enr["status"] == "ACTIVE"
