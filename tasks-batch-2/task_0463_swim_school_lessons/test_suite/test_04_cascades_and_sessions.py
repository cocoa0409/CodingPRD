"""Multi-hop cascades from student withdrawal, the assessment->enrollment state
precondition, and class-session open/close lifecycle (capacity copy, cascade
close, terminal lockdown).

Difficulty queue (A): transitive_cascade (student withdraw),
cross_entity_state_dependency (assessment submit -> enrollment active).
Corner queue (B): entities + state_machines session instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    assert_class_session,
    TEST_USERS,
    make_parent_headers,
    make_instructor_headers,
    set_clock,
    create_location,
    create_level,
    create_skill,
    create_instructor,
    create_class_session,
    open_session,
    create_parent,
    create_student,
    setup_parent_with_student,
    setup_open_session,
    setup_single_active_enrollment,
    create_active_enrollment,
    create_assessment,
    pause_enrollment,
    setup_capacity1_with_waitlist,
)

ADMIN = TEST_USERS["school_admin_headers"]


# ─── transitive_cascade: student withdraw -> promote waitlist ──────────────
def test_student_withdraw_withdraws_enrollment_and_promotes_waitlist(api):
    """PRD §3.2: "At the first level, every one of that student's enrollments in
    `ACTIVE`, `PAUSED`, or `WAITLISTED` status is moved to `WITHDRAWN`."
    PRD §3.2: "At the third level, each freed seat promotes the earliest-waiting
    candidate: among that session's `WAITLISTED` enrollments, the one with the
    earliest `joined_at` (ties broken by earliest `created_at`) is promoted to
    `ACTIVE`"

    Withdrawing P1's student (capacity-1 session) withdraws P1's ACTIVE
    enrollment and promotes P2's waitlisted enrollment to ACTIVE.

    Design: Difficulty/transitive_cascade/student_withdraw_promotes_waitlist_debits_promoted_parent
    """
    env = setup_capacity1_with_waitlist()
    headers = make_parent_headers(env["p1"]["id"])
    validate_success(api.withdraw_student(env["s1"]["id"], headers), 200)
    enr1 = validate_success(api.get_enrollment(env["enr1"]["id"], ADMIN), 200)
    enr2 = validate_success(api.get_enrollment(env["enr2"]["id"], ADMIN), 200)
    assert enr1["status"] == "WITHDRAWN"
    assert enr2["status"] == "ACTIVE"


def test_student_withdraw_settles_session_counts(api):
    """PRD §3.2: "the one with the earliest `joined_at` (ties broken by earliest
    `created_at`) is promoted to `ACTIVE`, which re-increments `enrolled_count`"
    PRD §2.5: "no count or balance is left stale after a cascade settles."

    After the depth-3 cascade (withdraw -> free seat -> promote) the capacity-1
    session settles at enrolled_count 1 and waitlist_count 0.

    Design: Difficulty/transitive_cascade/student_withdraw_promotes_waitlist_debits_promoted_parent
    """
    env = setup_capacity1_with_waitlist()
    headers = make_parent_headers(env["p1"]["id"])
    validate_success(api.withdraw_student(env["s1"]["id"], headers), 200)
    session = validate_success(api.get_class_session(env["session"]["id"], ADMIN), 200)
    assert session["enrolled_count"] == 1
    assert session["waitlist_count"] == 0


# ─── cross_entity_state_dependency: assessment submit needs ACTIVE enroll ──
def _level1_one_skill_active_enrollment(clock="2026-01-05T00:00:00Z"):
    set_clock(clock)
    location = create_location()
    level = create_level(min_age_months=36, max_age_months=200,
                         max_students_per_instructor=4)
    skill = create_skill(level["id"], name="Back Float 10s", weight=1.0)
    instructor = create_instructor(certified_level_ids=[level["id"]])
    session = create_class_session(location["id"], level["id"], instructor["id"])
    session = open_session(session["id"])
    parent, student = setup_parent_with_student(level["id"])
    enrollment = create_active_enrollment(parent, student, session)
    return {"level": level, "skill": skill, "instructor": instructor,
            "session": session, "parent": parent, "student": student,
            "enrollment": enrollment}


def test_submit_assessment_requires_active_enrollment(api):
    """PRD §3.7: "the enrollment must be `ACTIVE` (else
    `ERR_ENROLLMENT_NOT_ACTIVE`)"

    A DRAFT assessment whose enrollment is PAUSED before submit cannot be
    submitted — rejected ERR_ENROLLMENT_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/assessment_submit_requires_enrollment_active
    """
    env = _level1_one_skill_active_enrollment()
    asmt = create_assessment(
        env["instructor"], env["enrollment"]["id"],
        [{"skill_id": env["skill"]["id"], "score": 1.0}],
    )
    pause_enrollment(env["parent"], env["enrollment"]["id"])
    instr_headers = make_instructor_headers(env["instructor"]["id"])
    res = api.submit_assessment(asmt["id"], instr_headers)
    validate_error(res, "ERR_ENROLLMENT_NOT_ACTIVE")


def test_submit_assessment_succeeds_with_active_enrollment(api):
    """PRD §3.7: "Submitting an assessment moves it from `DRAFT` to `SUBMITTED`
    and freezes its scoring."

    The same assessment, left on its ACTIVE enrollment, submits successfully —
    confirming the ACTIVE enrollment state is what gates submission.

    Design: Difficulty/cross_entity_state_dependency/assessment_submit_requires_enrollment_active
    """
    env = _level1_one_skill_active_enrollment()
    asmt = create_assessment(
        env["instructor"], env["enrollment"]["id"],
        [{"skill_id": env["skill"]["id"], "score": 1.0}],
    )
    instr_headers = make_instructor_headers(env["instructor"]["id"])
    submitted = validate_success(api.submit_assessment(asmt["id"], instr_headers), 200)
    assert submitted["status"] == "SUBMITTED"


# ─── Corner queue (B): session capacity copy + close cascade + lockdown ────
def test_class_session_capacity_copied_from_level_ratio(api):
    """PRD §3.3: "At creation the session copies its `capacity` directly from the
    level's `max_students_per_instructor` — that copied value is the immutable
    seat quota for the life of the session — and initializes `enrolled_count` and
    `waitlist_count` to 0. A new session begins in `DRAFT` status"

    Creating a session at a ratio-4 level yields capacity 4, counts 0, DRAFT.

    Design: Corner/entities/create_class_session_capacity_copied_from_level_ratio
    """
    location = create_location()
    level = create_level(max_students_per_instructor=4)
    instructor = create_instructor(certified_level_ids=[level["id"]])
    res = api.create_class_session(
        {"location_id": location["id"], "level_id": level["id"],
         "instructor_id": instructor["id"], "lane_number": 1, "day_of_week": 1,
         "start_minute": 600, "end_minute": 645},
        ADMIN,
    )
    session = validate_success(res, 201)
    assert_class_session(session)
    assert session["capacity"] == 4
    assert session["enrolled_count"] == 0
    assert session["waitlist_count"] == 0
    assert session["status"] == "DRAFT"


def test_close_session_cascade_withdraws_all_enrollments(api):
    """PRD §3.5: "every enrollment of that session in `ACTIVE`, `PAUSED`, or
    `WAITLISTED` status is moved to `WITHDRAWN`, with each such withdrawal running
    its own seat and credit side effects, and afterward the session's
    `enrolled_count` and `waitlist_count` are recomputed to 0."

    Closing a capacity-1 session with one ACTIVE and one WAITLISTED enrollment
    withdraws both and drives both counts to 0.

    Design: Corner/state_machines/close_session_cascade_withdraws_all_enrollments
    """
    env = setup_capacity1_with_waitlist()
    closed = validate_success(api.close_class_session(env["session"]["id"], ADMIN), 200)
    assert closed["status"] == "CLOSED"
    enr1 = validate_success(api.get_enrollment(env["enr1"]["id"], ADMIN), 200)
    enr2 = validate_success(api.get_enrollment(env["enr2"]["id"], ADMIN), 200)
    assert enr1["status"] == "WITHDRAWN"
    assert enr2["status"] == "WITHDRAWN"
    session = validate_success(api.get_class_session(env["session"]["id"], ADMIN), 200)
    assert session["enrolled_count"] == 0
    assert session["waitlist_count"] == 0


def test_reopen_closed_session_rejected(api):
    """PRD §3.5: "`CLOSED` is a final state; no further transitions or
    enrollments are accepted."

    Opening a session already in terminal CLOSED is rejected ERR_INVALID_STATE.

    Design: Corner/state_machines/reopen_closed_session_returns_invalid_state
    """
    location = create_location()
    level = create_level(min_age_months=0, max_age_months=200,
                         max_students_per_instructor=4)
    instructor = create_instructor(certified_level_ids=[level["id"]])
    session = create_class_session(location["id"], level["id"], instructor["id"])
    open_session(session["id"])
    validate_success(api.close_class_session(session["id"], ADMIN), 200)
    res = api.open_class_session(session["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")
