"""Closing the marriage line of a single-wide home (PRD §3.7).

A single-section order has no marriage line to measure, so the empty joint set
is the boundary case: the closure is accepted rather than refused, the score is
exactly 0.00, the verdict is `NOT_APPLICABLE`, and the joint collection stays
empty behind its `set_job_id` filter.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_set_job,
    make_set_crew_lead_headers,
    setup_dispatched_set_job,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["network_admin_headers"]


def _close_line_of_single_wide():
    """Dispatch a single-section job, record no joints and close the line.

    Returns the dispatched-job scenario plus the response of the closure call,
    so a test can assert both the HTTP status and the written verdict.
    """
    scenario = setup_dispatched_set_job(section_count=1)
    response = api_client.close_marriage_line(
        scenario["set_job"]["id"],
        {},
        make_set_crew_lead_headers(scenario["set_crew"]["id"]),
    )
    return scenario, response


def test_single_section_line_closes_with_a_zero_score_and_a_not_applicable_verdict():
    """PRD §3.7: "The number of joints recorded on the job must equal the order's
    `section_count` less one, or zero when the order declares a single section;
    any other count is refused with `ERR_MARRIAGE_JOINT_COUNT_MISMATCH`, so a
    three-section home needs exactly two joints on file."
    PRD §3.7: "The verdict lands in `closure_status`: `NOT_APPLICABLE` when the
    joint count is zero, otherwise `PASS` when the `closure_score` is at most
    1.00, otherwise `FAIL`."
    PRD §3.7: "A single-section order therefore records no joints, closes with a
    `closure_score` of 0.00 and a `closure_status` of `NOT_APPLICABLE`, and passes
    the later gate vacuously."

    Design: Difficulty/boundary_precision_check/zero_joint_marriage_line_not_applicable
    """
    _scenario, response = _close_line_of_single_wide()

    job = validate_success(response, 200)

    assert_set_job(job)
    assert job["closure_status"] == "NOT_APPLICABLE", (
        "a zero joint count lands on NOT_APPLICABLE rather than PASS or FAIL, got "
        f"{job['closure_status']}"
    )
    assert job["closure_score"] == pytest.approx(0.00, abs=0.01), (
        f"a single-section order closes with a score of 0.00, got {job['closure_score']}"
    )


def test_single_section_closure_advances_progress_and_leaves_no_joints_on_file():
    """PRD §3.7: "The job's `SetCrewLead` closes the marriage line, which moves
    `progress_status` `DISPATCHED → SET_COMPLETE`."
    PRD §3.7: "A single-section order therefore records no joints, closes with a
    `closure_score` of 0.00 and a `closure_status` of `NOT_APPLICABLE`, and passes
    the later gate vacuously."
    PRD §2.3: "marriage joints accept `set_job_id`, which is the only discovery
    channel for joints because they are never embedded inside a set job's
    representation"

    Design: Difficulty/boundary_precision_check/zero_joint_marriage_line_not_applicable
    """
    scenario, response = _close_line_of_single_wide()

    job = validate_success(response, 200)

    assert job["progress_status"] == "SET_COMPLETE", (
        "closing the line moves the progress dimension to SET_COMPLETE, got "
        f"{job['progress_status']}"
    )

    joints, meta = validate_paginated(
        api_client.list_marriage_joints(
            ADMIN, params={"set_job_id": scenario["set_job"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"a single-wide records no joints at all, got total_count {meta['total_count']}"
    )
    assert joints == [], f"the joint listing must be empty, got {joints}"
