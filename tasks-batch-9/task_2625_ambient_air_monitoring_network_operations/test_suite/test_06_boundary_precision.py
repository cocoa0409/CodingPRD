"""Boundary cases: the inclusive completeness threshold and the empty rollup."""

from test_helpers import (
    ERR_PACKAGE_NOT_READY,
    PM_HEADERS,
    QA_HEADERS,
    apply_invalidation,
    assert_pct,
    canonical_environment,
    get_success_data,
    open_package,
    validate_error,
)


def _quarter_of_2160_hours(api):
    env = canonical_environment(api)
    batch = get_success_data(
        api.create_data_batch(
            {
                "monitor_id": env.monitor_id,
                "year": 2025,
                "quarter": 1,
                "scheduled_hour_count": 2160,
                "quarterly_mean_concentration": 9.0,
            },
            QA_HEADERS,
        )
    )
    return env, batch["id"]


def test_completeness_of_exactly_the_threshold_keeps_the_quarter_eligible(api):
    """540 of 2160 hours written off lands on 75.0 and stays eligible.

    PRD 3.4: "Seventh, `regulatory_use_eligible` is true exactly when that *rounded*
    `completeness_pct` is greater than or equal to the pollutant's
    `completeness_threshold_pct`; the comparison is inclusive at the threshold, and it uses
    the rounded figure and never the raw ratio."

    Design: Difficulty/boundary_precision_check/completeness_threshold_inclusive_at_exactly_75_pct
    """
    env, batch_id = _quarter_of_2160_hours(api)

    invalidation = apply_invalidation(api, batch_id, 0, 540, "QC_FAILURE")
    assert invalidation["hours_affected"] == 540

    quarter = get_success_data(api.get_data_batch(batch_id, QA_HEADERS))
    assert quarter["invalidated_hour_count"] == 540
    assert quarter["adjusted_scheduled_hour_count"] == 2160
    assert quarter["valid_hour_count"] == 1620
    assert_pct(quarter["completeness_pct"], 75.0)
    assert quarter["regulatory_use_eligible"] is True


def test_fifteen_more_invalidated_hours_drop_the_quarter_below_the_threshold(api):
    """A second, non-overlapping range takes completeness to 74.3 and eligibility to false.

    PRD 3.4: "Sixth, `completeness_pct` is `valid_hour_count` divided by
    `adjusted_scheduled_hour_count`, multiplied by 100 and rounded to one decimal place,
    except that when `adjusted_scheduled_hour_count` is zero the value is 0.0 rather than an
    error."

    Design: Difficulty/boundary_precision_check/completeness_threshold_inclusive_at_exactly_75_pct
    """
    env, batch_id = _quarter_of_2160_hours(api)
    apply_invalidation(api, batch_id, 0, 540, "QC_FAILURE")

    second = apply_invalidation(api, batch_id, 600, 615, "QC_FAILURE")
    assert second["hours_affected"] == 15

    quarter = get_success_data(api.get_data_batch(batch_id, QA_HEADERS))
    assert quarter["invalidated_hour_count"] == 555
    assert quarter["valid_hour_count"] == 1605
    assert_pct(quarter["completeness_pct"], 74.3)
    assert quarter["regulatory_use_eligible"] is False


def _draft_package_with_nothing_validated(api):
    env, batch_id = _quarter_of_2160_hours(api)
    open_package(env, year=2025)
    return env, batch_id


def test_a_package_with_no_member_quarters_cannot_be_submitted(api):
    """Zero selected quarters fail the at-least-one clause of the readiness gate.

    PRD 3.8: "Finally, `certification_ready` is true exactly when `included_batch_count` is
    at least 1 **and** `eligible_batch_count` equals `included_batch_count`; a single member
    quarter below its pollutant's completeness threshold makes the whole package unready, as
    does a package with no members at all."

    Design: Difficulty/boundary_precision_check/certification_package_zero_member_batches_blocks_submit
    """
    env, _batch_id = _draft_package_with_nothing_validated(api)

    response = api.submit_package(
        env.package_id,
        {"submission_note": "Attempting submission with nothing validated"},
        PM_HEADERS,
    )
    validate_error(response, ERR_PACKAGE_NOT_READY, 422)


def test_the_empty_rollup_pins_the_completeness_percentage_at_zero(api):
    """An empty selection yields 0.0 rather than a division error.

    PRD 3.8: "`rollup_completeness_pct` is computed from summed hours, not by averaging
    per-quarter percentages: sum `valid_hour_count` across the selected quarters, sum
    `adjusted_scheduled_hour_count` across the same quarters, divide the first total by the
    second, multiply by 100 and round to one decimal place — with the value taken as 0.0 when
    the second total is zero."

    Design: Difficulty/boundary_precision_check/certification_package_zero_member_batches_blocks_submit
    """
    env, batch_id = _draft_package_with_nothing_validated(api)
    api.submit_package(env.package_id, {}, PM_HEADERS)

    package = get_success_data(api.get_package(env.package_id, PM_HEADERS))
    assert package["included_batch_count"] == 0
    assert package["eligible_batch_count"] == 0
    assert_pct(package["rollup_completeness_pct"], 0.0)
    assert package["certification_ready"] is False
    assert package["status"] == "DRAFT"

    assert get_success_data(api.get_data_batch(batch_id, QA_HEADERS))[
        "submission_status"
    ] == "UNSUBMITTED"
