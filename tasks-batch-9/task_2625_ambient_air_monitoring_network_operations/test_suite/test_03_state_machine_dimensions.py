"""Non-linear state machines: parallel batch dimensions and the review cycle."""

from test_helpers import (
    EPA_HEADERS,
    PM_HEADERS,
    QA_HEADERS,
    add_wildfire_demonstration,
    assert_batch_dimensions,
    find_by_id,
    get_success_data,
    submit_demonstration,
    submitted_package,
    twelve_validated_quarters,
    validate_paginated,
    validate_success,
)


def _package_submitted_then_first_quarter_reopened(api):
    env = twelve_validated_quarters(api)
    submitted_package(env, year=2025)
    validate_success(
        api.reopen_batch(
            env.batch_id(2025, 1),
            {"reopen_reason": "Audit found a suspect zero-drift period"},
            QA_HEADERS,
        )
    )
    return env


def test_reopening_a_submitted_quarter_leaves_its_submission_standing_alone(api):
    """The validation move does not disturb the submission dimension.

    PRD 3.5: "A permitted reopen increments `reopen_count` by 1, clears
    `validated_by_user_id` to null, leaves `submission_status` untouched, and
    increments the quarter's `version`."

    Design: Difficulty/non_linear_state_machine/data_batch_validation_and_submission_dimensions_move_independently
    """
    env = _package_submitted_then_first_quarter_reopened(api)

    reopened = env.read_batch(2025, 1)
    assert_batch_dimensions(reopened, "REOPENED", "SUBMITTED")
    assert reopened["reopen_count"] == 1
    assert reopened["validated_by_user_id"] is None


def test_the_other_quarters_and_the_package_are_untouched_by_the_reopen(api):
    """Sibling quarters keep both dimensions and the package stays submitted.

    PRD 3.4: "The two status fields are **independent dimensions on the same row**: a
    quarter's quality-assurance standing and its national-database standing evolve
    separately, and an operation that moves one leaves the other exactly where it was."

    Design: Difficulty/non_linear_state_machine/data_batch_validation_and_submission_dimensions_move_independently
    """
    env = _package_submitted_then_first_quarter_reopened(api)

    assert_batch_dimensions(env.read_batch(2025, 2), "VALIDATED", "SUBMITTED")
    assert env.read_batch(2023, 1)["submission_status"] == "UNSUBMITTED"

    package = get_success_data(api.get_package(env.package_id, PM_HEADERS))
    assert package["status"] == "SUBMITTED"
    assert package["included_batch_count"] == 3


def _demonstration_through_the_info_request_cycle(api):
    env = twelve_validated_quarters(api)
    add_wildfire_demonstration(env)
    submit_demonstration(env, submission_note="Initial demonstration package")
    validate_success(
        api.request_demonstration_info(
            env.demonstration_id,
            {"info_request_note": "Provide HYSPLIT back trajectories and satellite imagery"},
            EPA_HEADERS,
        )
    )
    submit_demonstration(env, submission_note="Trajectories and imagery attached")
    decided = validate_success(
        api.decide_demonstration(
            env.demonstration_id,
            {
                "determination": "CONCUR",
                "determination_note": "Clear causal relationship demonstrated",
            },
            EPA_HEADERS,
        )
    )
    return env, decided


def test_the_information_request_cycle_returns_the_row_to_submitted(api):
    """One loop through INFO_REQUESTED leaves the counter at 1 and concurrence reachable.

    PRD 3.6: "The manager then resubmits, advancing `INFO_REQUESTED → SUBMITTED` and
    closing the review cycle."

    Design: Difficulty/non_linear_state_machine/event_demonstration_info_request_cycle_returns_to_submitted
    """
    env, decided = _demonstration_through_the_info_request_cycle(api)

    assert decided["info_request_count"] == 1
    assert decided["status"] == "CONCURRED"
    assert decided["determined_by_user_id"] == "epa-1"
    assert decided["determined_at"].startswith("2026-01-05T00:00:00")


def test_the_exclusion_only_becomes_effective_at_the_end_of_the_cycle(api):
    """Proposed hours stay a claim until the determination concurs.

    PRD 3.6: "In the second hop, every exclusion under this demonstration whose
    `status` is `PROPOSED` moves to `EFFECTIVE`, has `effective_at` stamped from the
    logical clock, and has its `version` incremented; the demonstration's
    `excluded_hour_total` is then recomputed as the sum of `hours_affected` across its
    effective exclusions."

    Design: Difficulty/non_linear_state_machine/event_demonstration_info_request_cycle_returns_to_submitted
    """
    env, decided = _demonstration_through_the_info_request_cycle(api)

    assert decided["excluded_hour_total"] == 192

    exclusions, _ = validate_paginated(
        api.list_demonstration_exclusions(env.demonstration_id, PM_HEADERS)
    )
    exclusion = find_by_id(exclusions, env.exclusion_id)
    assert exclusion["status"] == "EFFECTIVE"
    assert exclusion["effective_at"].startswith("2026-01-05T00:00:00")

    quarter = env.read_batch(2024, 3)
    assert quarter["event_excluded_hour_count"] == 192
    assert quarter["adjusted_scheduled_hour_count"] == 2016
