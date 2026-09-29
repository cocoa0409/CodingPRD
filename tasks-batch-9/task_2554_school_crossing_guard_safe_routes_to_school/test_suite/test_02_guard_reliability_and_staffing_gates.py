"""Guard reliability, certification and the safety gates on staffing a post.

A guard carries two reliability figures computed from one absence history, and
the staffing endpoint runs four safety gates on the guard before it looks at the
calendar at all. These tests pin both reliability variants against the same
absences and hold the gate ordering to the sequence the PRD declares.
"""
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_guard, assert_post_assignment
from test_helpers.factories import create_assignment_payload, certify_guard_payload
from test_helpers.fixtures import (
    SUPERVISOR,
    create_active_post,
    file_absence,
    read_assignment,
    read_guard,
    read_post,
    setup_guard_in_training,
    setup_staffed_post,
    setup_warranted_intersection,
)

THREE_ILLNESS_DATES = ["2026-09-08", "2026-09-09", "2026-09-10"]


def test_three_excused_absences_produce_two_different_reliability_figures(api):
    """The rolling and season-to-date variants charge the same absences at
    different rates, so one guard row carries two different scores.

    PRD: "Its coefficients are 4.0 per absence and a further 6.0 per unexcused
    absence" ... "Its coefficients are 2.5 per absence and a further 7.5 per
    unexcused absence, forgiving excused absences more and punishing unexcused
    ones harder."

    Design: Difficulty/dual_variant_calc/guard_reliability_rolling_vs_season_divergence
    """
    scenario = setup_staffed_post()
    for absence_date in THREE_ILLNESS_DATES:
        file_absence(scenario["assignment"]["id"], absence_date=absence_date)

    guard = read_guard(scenario["guard"]["id"])

    assert_guard(guard)
    assert guard["reliability_score_rolling_90d"] == 91.00
    assert guard["reliability_score_season_to_date"] == 95.50
    assert round(guard["reliability_score_season_to_date"]
                 - guard["reliability_score_rolling_90d"], 2) == 4.50


def test_a_rolling_score_above_the_floor_leaves_certification_and_duty_intact(api):
    """91.00 sits above the reliability floor, so the suspension cascade must not fire.

    PRD: "for a guard whose `certification_status` is `CERTIFIED`, that guard
    moves `CERTIFIED → SUSPENDED` with `suspension_reason` set to
    `RELIABILITY_BREACH`".

    Design: Difficulty/dual_variant_calc/guard_reliability_rolling_vs_season_divergence
    """
    scenario = setup_staffed_post()
    for absence_date in THREE_ILLNESS_DATES:
        file_absence(scenario["assignment"]["id"], absence_date=absence_date)

    guard = read_guard(scenario["guard"]["id"])
    assignment = read_assignment(scenario["assignment"]["id"])

    assert guard["certification_status"] == "CERTIFIED"
    assert guard["suspension_reason"] is None
    assert guard["duty_status"] == "ASSIGNED"
    assert guard["training_hours_completed"] == 12
    assert assignment["status"] == "SCHEDULED"
    assert assignment["vacated_reason"] is None


def test_an_uncertified_guard_cannot_be_installed_on_an_active_post(api):
    """The first safety gate reads the guard's certification dimension, and a guard
    with complete equipment who has never been certified is still refused.

    PRD: "The named guard's `certification_status` must be `CERTIFIED`, or the
    refusal is `ERR_GUARD_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/assignment_creation_gated_on_guard_certification_state
    """
    scenario = setup_warranted_intersection()
    post = create_active_post(scenario["intersection"]["id"])
    guard = setup_guard_in_training()
    assert guard["certification_status"] == "IN_TRAINING"
    assert guard["equipment_complete"] is True
    assert guard["duty_status"] == "UNASSIGNED"
    assert guard["training_hours_completed"] == 12

    response = api.create_assignment(
        post["id"],
        create_assignment_payload(guard["id"], post["version"]),
        SUPERVISOR)

    error = validate_error(response, ApiErrorId.ERR_GUARD_NOT_CERTIFIED.value)
    assert error["error_id"] != ApiErrorId.ERR_GUARD_EQUIPMENT_INCOMPLETE.value
    assert error["error_id"] != ApiErrorId.ERR_GUARD_ON_LEAVE.value
    assert error["error_id"] != ApiErrorId.ERR_GUARD_CERT_EXPIRED.value


def test_certifying_the_guard_makes_the_identical_staffing_request_succeed(api):
    """Only the guard's certification state changes between the refused call and
    the accepted one, and the refused call must not have consumed the post's
    version token.

    PRD: "On success the assignment is created in `SCHEDULED`, with `shift`
    copied from the parent post's `required_shift`, `open_absence_count` at 0 and
    `coverage_state` at `STAFFED`."

    Design: Difficulty/cross_entity_state_dependency/assignment_creation_gated_on_guard_certification_state
    """
    scenario = setup_warranted_intersection()
    post = create_active_post(scenario["intersection"]["id"])
    guard = setup_guard_in_training()
    post_version = post["version"]

    validate_error(
        api.create_assignment(
            post["id"], create_assignment_payload(guard["id"], post_version),
            SUPERVISOR),
        ApiErrorId.ERR_GUARD_NOT_CERTIFIED.value)
    assert read_post(post["id"])["version"] == post_version

    certified = validate_success(api.certify_guard(
        guard["id"], certify_guard_payload(), SUPERVISOR))
    assert certified["certification_status"] == "CERTIFIED"
    assert certified["certification_expires_on"] == "2027-06-30"

    assignment = validate_success(
        api.create_assignment(
            post["id"], create_assignment_payload(guard["id"], post_version),
            SUPERVISOR),
        201)

    assert_post_assignment(assignment)
    assert assignment["status"] == "SCHEDULED"
    assert assignment["guard_id"] == guard["id"]
    assert assignment["shift"] == "AM"
    assert read_guard(guard["id"])["duty_status"] == "ASSIGNED"
    assert read_post(post["id"])["coverage_status"] == "COVERED"


def test_a_certification_lapsing_mid_window_is_reported_before_the_overlap(api):
    """The requested window both runs past the guard's certification expiry and
    overlaps an existing AM assignment; the safety gate answers first.

    PRD: "The guard's `certification_expires_on` must be on or after the
    assignment's `end_date`, so that a certification lapsing mid-window is caught
    up front rather than discovered in February; a shortfall is
    `ERR_GUARD_CERT_EXPIRED`." ... "Two temporal gates follow, in this order."

    Design: Difficulty/priority_pair_validation_conflict/expiring_certification_beats_assignment_overlap_on_same_guard
    """
    scenario = setup_staffed_post(certification_expires_on="2026-09-30")
    post_b = create_active_post(scenario["intersection"]["id"],
                               post_label="Maple SE corner", required_shift="AM")
    post_b_version = post_b["version"]

    response = api.create_assignment(
        post_b["id"],
        create_assignment_payload(scenario["guard"]["id"], post_b_version,
                                  start_date="2026-09-15", end_date="2026-10-15"),
        SUPERVISOR)

    error = validate_error(response, ApiErrorId.ERR_GUARD_CERT_EXPIRED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_ASSIGNMENT_OVERLAP.value
    assert response.status_code != 409
    incumbent = read_assignment(scenario["assignment"]["id"])
    assert incumbent["status"] == "SCHEDULED"
    assert incumbent["end_date"] == "2026-09-18"
    assert read_post(post_b["id"])["version"] == post_b_version
    on_post_b, meta = validate_paginated(
        api.list_post_assignments(SUPERVISOR, {"guard_post_id": post_b["id"]}))
    assert on_post_b == []
    assert meta["total_count"] == 0


def test_the_same_window_is_refused_for_overlap_once_certification_reaches_far_enough(api):
    """With the certification gate satisfied the very same window is still refused,
    which is what makes the ordering of the two gates observable.

    PRD: "the request is refused with `ERR_ASSIGNMENT_OVERLAP` (HTTP 409) when the
    same guard already holds an assignment in `SCHEDULED` or `ACTIVE` whose date
    range overlaps the new one on closed intervals".

    Design: Difficulty/priority_pair_validation_conflict/expiring_certification_beats_assignment_overlap_on_same_guard
    """
    scenario = setup_staffed_post(certification_expires_on="2027-06-30")
    post_b = create_active_post(scenario["intersection"]["id"],
                               post_label="Maple SE corner", required_shift="AM")

    response = api.create_assignment(
        post_b["id"],
        create_assignment_payload(scenario["guard"]["id"], post_b["version"],
                                  start_date="2026-09-15", end_date="2026-10-15"),
        SUPERVISOR)

    validate_error(response, ApiErrorId.ERR_ASSIGNMENT_OVERLAP.value, 409)
    incumbent = read_assignment(scenario["assignment"]["id"])
    assert incumbent["status"] == "SCHEDULED"
    assert incumbent["end_date"] == "2026-09-18"
