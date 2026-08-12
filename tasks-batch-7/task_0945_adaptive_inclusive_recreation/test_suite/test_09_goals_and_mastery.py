"""Progress, mastery and the session debrief."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_same_instant,
    create_active_participant,
    create_confirmed_enrollment,
    create_fee_band,
    create_goal,
    create_program,
    create_session,
    create_staff,
    lock_staffing,
    open_session,
    propose_assignment,
    rate_goal,
    read_enrollment,
    read_goal,
    read_session,
    record_attendance,
    set_clock,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import ADMIN
from test_helpers.test_users import make_activity_lead_headers


def _weekly_series_attended(count, goal_overrides=None, attend=None):
    """`count` weekly sessions, each staffed and locked, with one participant
    confirmed on every one and attendance recorded where `attend` says so.

    Returns (goal, staff_id, sessions, enrollments).
    """
    create_fee_band()
    program = create_program(
        name="Adaptive Swim Skills", activity_type="AQUATICS", scheduled_session_count=count
    )
    staff_id = create_staff()["id"]
    who = create_active_participant()
    participant_id = who["participant"]["id"]
    goal = create_goal(participant_id, **(goal_overrides or {}))

    starts = ["2026-06-01T09:00:00Z", "2026-06-08T09:00:00Z", "2026-06-15T09:00:00Z"]
    ends = ["2026-06-01T11:00:00Z", "2026-06-08T11:00:00Z", "2026-06-15T11:00:00Z"]
    sessions, enrollments = [], []
    for index in range(count):
        session = create_session(
            program["id"], start_at=starts[index], end_at=ends[index], slot_capacity=2
        )
        open_session(session["id"])
        sessions.append(session)
    for index, session in enumerate(sessions):
        enrollments.append(create_confirmed_enrollment(participant_id, session["id"]))
        propose_assignment(session["id"], staff_id)
        lock_staffing(session["id"], staff_id)

    attend = range(count) if attend is None else attend
    clocks = ["2026-06-01T10:00:00Z", "2026-06-08T10:00:00Z", "2026-06-15T10:00:00Z"]
    for index in attend:
        set_clock(clocks[index])
        record_attendance(enrollments[index]["id"], staff_id, "ATTENDED")
    return goal, staff_id, sessions, enrollments


def test_goal_enters_mastered_once_the_rolling_window_is_full_of_hits():
    """PRD §3.9: "Under `N_OF_M`, take the first `mastery_window_m` entries of
    that ordering as the window; the goal is mastered when the window is full —
    that is, when at least `mastery_window_m` ratings exist — and the number of
    entries in it whose `score` is at or above `mastery_criterion_score` is at
    least `mastery_hits_n`."
    PRD §3.9: "A goal moves from `ACTIVE` to `MASTERED` when the recomputation
    says true and from `MASTERED` back to `ACTIVE` when it says false, and both
    directions are driven only by the system, immediately after a rating is
    persisted."

    Design: Difficulty/non_linear_state_machine/goal_enters_then_leaves_mastered_as_newer_ratings_arrive
    """
    goal, staff_id, sessions, _enrollments = _weekly_series_attended(
        3,
        goal_overrides={
            "title": "Independent pool transfers",
            "mastery_mode": "N_OF_M",
            "mastery_criterion_score": 4,
            "mastery_window_m": 2,
            "mastery_hits_n": 2,
        },
    )

    rate_goal(goal["id"], sessions[0]["id"], 5, staff_id, note="clean transfer")
    assert read_goal(goal["id"])["status"] == "ACTIVE", (
        "the window holds only 1 of the required 2 entries"
    )

    rate_goal(goal["id"], sessions[1]["id"], 5, staff_id, note="clean transfer")
    assert read_goal(goal["id"])["status"] == "MASTERED"


def test_a_later_weak_rating_knocks_the_goal_back_out_of_mastery():
    """PRD §3.9: "Mastery is explicitly **not monotone**. A goal moves from
    `ACTIVE` to `MASTERED` when the recomputation says true and from `MASTERED`
    back to `ACTIVE` when it says false, and both directions are driven only by
    the system, immediately after a rating is persisted."
    PRD §3.9: "Order the goal's ratings by `rated_session_start_at` descending,
    breaking ties by `created_at` descending — note that this is the order of the
    *sessions rated*, not the order the ratings were entered, so a rating
    recorded late about an early session sorts to the back."
    PRD §3.9: "On success the server pins `rated_session_start_at` as a copy of
    the rated session's `start_at`, raises the goal's `rating_count` by one,
    re-derives mastery, and raises the goal's `version` by one."

    Design: Difficulty/non_linear_state_machine/goal_enters_then_leaves_mastered_as_newer_ratings_arrive
    """
    goal, staff_id, sessions, _enrollments = _weekly_series_attended(
        3,
        goal_overrides={
            "title": "Independent pool transfers",
            "mastery_mode": "N_OF_M",
            "mastery_criterion_score": 4,
            "mastery_window_m": 2,
            "mastery_hits_n": 2,
        },
    )
    rate_goal(goal["id"], sessions[0]["id"], 5, staff_id, note="clean transfer")
    rate_goal(goal["id"], sessions[1]["id"], 5, staff_id, note="clean transfer")
    assert read_goal(goal["id"])["status"] == "MASTERED"

    third = rate_goal(
        goal["id"], sessions[2]["id"], 2, staff_id, note="needed two prompts"
    )

    after = read_goal(goal["id"])
    assert after["status"] == "ACTIVE", (
        "the newest window holds one miss and one hit, below the required two hits"
    )
    assert after["rating_count"] == 3
    assert_same_instant(
        third["rated_session_start_at"],
        read_session(sessions[2]["id"])["start_at"],
        label="rated_session_start_at",
    )


def test_goal_rating_rungs_reject_unattended_sessions_and_duplicates():
    """PRD §3.9: "Three checks guard the write, in ladder order: the goal's
    participant must hold an enrolment on the rated session at all, or the
    cross-reference fails with `ERR_PROGRAM_SESSION_MISMATCH`; the goal must not
    already carry a rating for that same session, or it is
    `ERR_DUPLICATE_GOAL_RATING`; and the participant's enrolment on that session
    must have `enrollment_status` `ATTENDED`, or it is
    `ERR_RATING_SESSION_NOT_ATTENDED`."

    Design: Corner/validations/goal_rating_rungs_reject_unattended_sessions_and_duplicates
    """
    goal, staff_id, sessions, enrollments = _weekly_series_attended(
        2,
        goal_overrides={
            "title": "Independent transfers",
            "mastery_mode": "CONSECUTIVE",
            "mastery_criterion_score": 4,
            "mastery_window_m": 3,
            "mastery_hits_n": 3,
        },
        attend=[0],
    )
    rate_goal(goal["id"], sessions[0]["id"], 5, staff_id, note="first rating")

    assert read_enrollment(enrollments[1]["id"])["enrollment_status"] == "CONFIRMED"
    validate_error(
        api_client.create_goal_rating(
            goal["id"],
            {"session_id": sessions[1]["id"], "score": 4, "note": "not attended yet"},
            make_activity_lead_headers(staff_id),
        ),
        ApiErrorId.ERR_RATING_SESSION_NOT_ATTENDED.value,
        expected_status=422,
    )

    validate_error(
        api_client.create_goal_rating(
            goal["id"],
            {"session_id": sessions[0]["id"], "score": 3, "note": "second attempt"},
            make_activity_lead_headers(staff_id),
        ),
        ApiErrorId.ERR_DUPLICATE_GOAL_RATING.value,
        expected_status=409,
    )

    assert read_goal(goal["id"])["rating_count"] == 1
    _rows, meta = validate_paginated(
        api_client.list_goal_ratings(ADMIN, params={"goal_id": goal["id"]})
    )
    assert meta["total_count"] == 1
