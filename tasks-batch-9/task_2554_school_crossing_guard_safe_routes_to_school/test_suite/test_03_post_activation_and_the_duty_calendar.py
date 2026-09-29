"""Activating posts against the warrant, and fitting assignments onto a calendar.

A guard post may only open where the warrant allows it, and a guard's duty
calendar is compared on closed intervals through a shift-conflict matrix. These
tests cover both gates and the coverage arithmetic that follows a successful
activation.
"""
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_guard_post,
    assert_same_instant,
    assert_post_assignment,
    assert_school,
)
from test_helpers.factories import create_assignment_payload, create_guard_post_payload
from test_helpers.fixtures import (
    ADMIN,
    SUPERVISOR,
    create_active_post,
    create_school,
    read_assignment,
    read_guard,
    read_intersection,
    read_post,
    read_school,
    setup_finalized_study,
    setup_staffed_post,
)

# A 25 mph crossing with no crash history scores 59.00 on these two sessions,
# one point short of the warrant threshold.
UNWARRANTED_AM_SESSION = {
    "session_date": "2026-09-08",
    "period": "AM_ARRIVAL",
    "observed_minutes": 60,
    "child_count": 60,
    "adult_count": 5,
    "vehicle_count": 1800,
    "adequate_gaps": 24,
}
UNWARRANTED_PM_SESSION = {
    "session_date": "2026-09-09",
    "period": "PM_DISMISSAL",
    "observed_minutes": 60,
    "child_count": 40,
    "adult_count": 4,
    "vehicle_count": 1400,
    "adequate_gaps": 16,
}


def _school_with_warranted_and_unwarranted_crossings():
    school = create_school()
    warranted = setup_finalized_study(school=school,
                                      cross_streets="Maple St & 3rd Ave")
    unwarranted = setup_finalized_study(
        school=school, cross_streets="Birch St & 4th Ave", speed_limit_mph=25,
        crashes=[], sessions=[UNWARRANTED_AM_SESSION, UNWARRANTED_PM_SESSION])
    return school, warranted, unwarranted


def test_a_post_at_an_unwarranted_crossing_cannot_be_activated(api):
    """Activation reads the parent intersection's warrant status, and a negative
    determination closes the post.

    PRD: "Next, the parent intersection's `warrant_status` must be `WARRANTED` or
    `CONDITIONAL`; anything else — `NOT_STUDIED`, `UNDER_STUDY` or
    `NOT_WARRANTED` — is refused with `ERR_POST_NOT_WARRANTED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/post_activation_gated_on_intersection_warrant_status
    """
    _, warranted, unwarranted = _school_with_warranted_and_unwarranted_crossings()
    assert read_intersection(
        unwarranted["intersection"]["id"])["warrant_status"] == "NOT_WARRANTED"
    assert read_intersection(
        unwarranted["intersection"]["id"])["latest_warrant_score"] == 59.00
    assert read_intersection(
        warranted["intersection"]["id"])["warrant_status"] == "WARRANTED"
    post = validate_success(api.create_guard_post(
        create_guard_post_payload(unwarranted["intersection"]["id"],
                                  post_label="Birch NE corner"), SUPERVISOR), 201)

    response = api.activate_guard_post(post["id"], ADMIN)

    error = validate_error(response, ApiErrorId.ERR_POST_NOT_WARRANTED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_POST_NOT_ACTIVATABLE.value
    assert error["error_id"] != ApiErrorId.ERR_POST_SHIFT_NOT_PERMITTED.value
    unchanged = read_post(post["id"])
    assert unchanged["status"] == "PROPOSED"
    assert unchanged["activated_at"] is None


def test_activating_the_first_post_leaves_the_school_uncovered(api):
    """A freshly activated post has no assignment yet, so activation alone can
    degrade the school's posture.

    PRD: "because a freshly activated post has no assignment yet and is therefore
    `UNSTAFFED`, it counts as uncovered, and activating a post can degrade a
    school's posture on its own."

    Design: Difficulty/cross_entity_state_dependency/post_activation_gated_on_intersection_warrant_status
    """
    school, warranted, _ = _school_with_warranted_and_unwarranted_crossings()
    post = validate_success(api.create_guard_post(
        create_guard_post_payload(warranted["intersection"]["id"]), SUPERVISOR), 201)

    activated = validate_success(api.activate_guard_post(post["id"], ADMIN))

    assert_guard_post(activated)
    assert activated["status"] == "ACTIVE"
    assert_same_instant(activated["activated_at"], "2026-08-01T00:00:00Z",
                        "GuardPost.activated_at")
    assert activated["coverage_status"] == "UNSTAFFED"
    updated_school = read_school(school["id"])
    assert_school(updated_school)
    assert updated_school["active_post_count"] == 1
    assert updated_school["covered_post_count"] == 0
    assert updated_school["uncovered_post_count"] == 1
    assert updated_school["coverage_rate_pct"] == 0.00
    assert updated_school["coverage_posture"] == "SUSPENDED"


def test_a_window_sharing_one_day_with_an_existing_assignment_is_refused(api):
    """Closed intervals share the incumbent's last day, so 2026-09-18 collides.

    PRD: "the new `start_date` falls on or before the existing `end_date` and the
    new `end_date` falls on or after the existing `start_date`".

    Design: Difficulty/resource_temporal_overlap/guard_assignment_closed_interval_overlap_and_shift_matrix
    """
    scenario = setup_staffed_post()
    post_b = create_active_post(scenario["intersection"]["id"],
                               post_label="Maple SE corner", required_shift="AM")
    post_b_version = post_b["version"]

    response = api.create_assignment(
        post_b["id"],
        create_assignment_payload(scenario["guard"]["id"], post_b_version,
                                  start_date="2026-09-18", end_date="2026-09-25"),
        SUPERVISOR)

    validate_error(response, ApiErrorId.ERR_ASSIGNMENT_OVERLAP.value, 409)
    assert read_post(post_b["id"])["version"] == post_b_version
    on_post_b, meta = validate_paginated(
        api.list_post_assignments(SUPERVISOR, {"guard_post_id": post_b["id"]}))
    assert on_post_b == []
    assert meta["total_count"] == 0
    incumbent = read_assignment(scenario["assignment"]["id"])
    assert incumbent["status"] == "SCHEDULED"
    assert incumbent["end_date"] == "2026-09-18"


def test_a_back_to_back_window_starting_the_next_day_is_accepted(api):
    """One day later there is no shared day, and back-to-back duty is legal.

    PRD: "Back-to-back windows are legal — when the new `start_date` is the day
    immediately after the existing `end_date` there is no overlap."

    Design: Difficulty/resource_temporal_overlap/guard_assignment_closed_interval_overlap_and_shift_matrix
    """
    scenario = setup_staffed_post()
    post_b = create_active_post(scenario["intersection"]["id"],
                               post_label="Maple SE corner", required_shift="AM")

    assignment = validate_success(
        api.create_assignment(
            post_b["id"],
            create_assignment_payload(scenario["guard"]["id"], post_b["version"],
                                      start_date="2026-09-19",
                                      end_date="2026-09-25"),
            SUPERVISOR),
        201)

    assert_post_assignment(assignment)
    assert assignment["status"] == "SCHEDULED"
    assert assignment["start_date"] == "2026-09-19"
    assert assignment["shift"] == "AM"
    incumbent = read_assignment(scenario["assignment"]["id"])
    assert incumbent["status"] == "SCHEDULED"
    assert incumbent["end_date"] == "2026-09-18"
    assert read_guard(scenario["guard"]["id"])["duty_status"] == "ASSIGNED"
    assert read_post(post_b["id"])["coverage_status"] == "COVERED"


def test_an_identical_window_on_an_afternoon_post_does_not_conflict(api):
    """Overlap alone is not enough: the two shifts must also conflict, and a
    morning shift does not conflict with an afternoon one.

    PRD: "`AM` conflicts only with `AM` and with `BOTH`; `PM` conflicts only with
    `PM` and with `BOTH`."

    Design: Difficulty/resource_temporal_overlap/guard_assignment_closed_interval_overlap_and_shift_matrix
    """
    scenario = setup_staffed_post(required_shift="AM")
    post_c = create_active_post(scenario["intersection"]["id"],
                               post_label="Maple SW corner", required_shift="PM")

    assignment = validate_success(
        api.create_assignment(
            post_c["id"],
            create_assignment_payload(scenario["guard"]["id"], post_c["version"],
                                      start_date="2026-09-08",
                                      end_date="2026-09-18"),
            SUPERVISOR),
        201)

    assert assignment["status"] == "SCHEDULED"
    assert assignment["shift"] == "PM"
    assert assignment["start_date"] == "2026-09-08"
    assert assignment["end_date"] == "2026-09-18"
    incumbent = read_assignment(scenario["assignment"]["id"])
    assert incumbent["status"] == "SCHEDULED"
    assert incumbent["end_date"] == "2026-09-18"
    assert read_post(scenario["post"]["id"])["coverage_status"] == "COVERED"
    assert read_post(post_c["id"])["coverage_status"] == "COVERED"
