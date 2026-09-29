"""Multi-hop cascades fired by a single regional decision."""

import pytest

from test_helpers import (
    EPA_HEADERS,
    PM_HEADERS,
    QA_HEADERS,
    add_wildfire_demonstration,
    approved_assessment,
    assert_batch_dimensions,
    assert_pct,
    compute_design_value,
    find_by_id,
    get_success_data,
    submit_demonstration,
    submitted_change_request,
    submitted_package,
    twelve_validated_quarters,
    validate_paginated,
    validate_success,
)


def _concurrence_over_a_provisional_design_value(api):
    env = twelve_validated_quarters(api)
    design_value = compute_design_value(env, 2025, "WITH_EVENT_DATA")
    add_wildfire_demonstration(env)
    submit_demonstration(env)
    validate_success(
        api.decide_demonstration(
            env.demonstration_id,
            {"determination": "CONCUR", "determination_note": "Wildfire influence demonstrated"},
            EPA_HEADERS,
        )
    )
    return env, design_value


def test_concurrence_reaches_the_quarter_s_hour_accounting(api):
    """The effective exclusion drops the quarter's denominator inside the same request.

    PRD 3.6: "In the third hop, every quarter referenced by those newly effective
    exclusions re-runs hour accounting, which raises `event_excluded_hour_count`, lowers
    `adjusted_scheduled_hour_count` by the same amount, and refreshes `completeness_pct`
    and `regulatory_use_eligible` accordingly."

    Design: Difficulty/transitive_cascade/concurrence_cascade_exclusion_to_hour_accounting_to_design_value
    """
    env, _ = _concurrence_over_a_provisional_design_value(api)

    demonstration = get_success_data(api.get_demonstration(env.demonstration_id, PM_HEADERS))
    assert demonstration["status"] == "CONCURRED"

    exclusions, _meta = validate_paginated(
        api.list_demonstration_exclusions(env.demonstration_id, PM_HEADERS)
    )
    assert find_by_id(exclusions, env.exclusion_id)["status"] == "EFFECTIVE"

    quarter = env.read_batch(2024, 3)
    assert quarter["event_excluded_hour_count"] == 192
    assert quarter["adjusted_scheduled_hour_count"] == 2016
    assert quarter["valid_hour_count"] == 2016
    assert_pct(quarter["completeness_pct"], 100.0)
    assert quarter["validation_status"] == "VALIDATED"


def test_the_changed_hour_accounting_supersedes_the_provisional_design_value(api):
    """The fourth hop retires the determination that rested on the old hours.

    PRD 3.6: "In the fourth hop, because those quarters' completeness figures changed,
    every provisional design value for the affected quarter's site and pollutant whose
    `period_end_year` is the quarter's year, the year after, or two years after moves to
    `SUPERSEDED` with `stale_reason` set to `EVENT_EXCLUSION_APPLIED`."

    Design: Difficulty/transitive_cascade/concurrence_cascade_exclusion_to_hour_accounting_to_design_value
    """
    env, design_value = _concurrence_over_a_provisional_design_value(api)

    stale = get_success_data(api.get_design_value(design_value["id"], PM_HEADERS))
    assert stale["status"] == "SUPERSEDED"
    assert stale["stale_reason"] == "EVENT_EXCLUSION_APPLIED"
    assert stale["design_value"] == pytest.approx(9.1, abs=0.001)


def _shutdown_approved_over_a_submitted_package(api):
    env = twelve_validated_quarters(api)
    submitted_package(env, year=2025)
    validate_success(
        api.reopen_batch(
            env.batch_id(2025, 1),
            {"reopen_reason": "Audit flagged the first quarter for re-review"},
            QA_HEADERS,
        )
    )
    approved_assessment(env, cycle_year=2026)
    submitted_change_request(
        env,
        request_type="SHUTDOWN",
        justification="Lease terminated and the assessment shows the site is redundant",
    )
    decided = validate_success(
        api.decide_change_request(
            env.change_request_id,
            {"decision": "APPROVE", "decision_note": "Shutdown approved effective immediately"},
            EPA_HEADERS,
        )
    )
    return env, decided


def test_shutdown_approval_walks_site_instrument_and_quarter(api):
    """Hops one to three: the site closes, its instrument is decommissioned, its
    unfinished quarter is written off.

    PRD 3.9: "The third hop, fired because those instruments were decommissioned, moves
    every quarter of theirs whose `validation_status` is `RAW`, `IN_VALIDATION` or
    `REOPENED` to `INVALIDATED` with `batch_invalidation_reason` set to
    `MONITOR_DECOMMISSIONED`; quarters already `VALIDATED` or already `INVALIDATED` are
    left alone."

    Design: Difficulty/transitive_cascade/site_shutdown_cascade_monitor_batch_package_submission
    """
    env, decided = _shutdown_approved_over_a_submitted_package(api)

    assert decided["status"] == "APPROVED"
    assert decided["effective_at"].startswith("2026-01-05T00:00:00")
    assert env.read_site()["status"] == "SHUTDOWN"
    assert env.read_monitor()["monitor_status"] == "DECOMMISSIONED"

    written_off = env.read_batch(2025, 1)
    assert written_off["validation_status"] == "INVALIDATED"
    assert written_off["batch_invalidation_reason"] == "MONITOR_DECOMMISSIONED"

    network = env.read_network()
    assert network["shutdown_site_count"] == 1
    assert network["operating_site_count"] == 0


def test_shutdown_approval_returns_the_package_and_unsubmits_its_quarters(api):
    """Hops four and five: the package falls back to draft and its quarters follow.

    PRD 3.9: "The fifth hop, fired because those packages returned to draft, demotes
    every quarter matching such a package's network, pollutant and year whose
    `submission_status` is `SUBMITTED` back to `UNSUBMITTED`."

    Design: Difficulty/transitive_cascade/site_shutdown_cascade_monitor_batch_package_submission
    """
    env, _ = _shutdown_approved_over_a_submitted_package(api)

    package = get_success_data(api.get_package(env.package_id, PM_HEADERS))
    assert package["status"] == "DRAFT"
    assert package["rejection_count"] == 1

    assert env.read_batch(2025, 1)["submission_status"] == "UNSUBMITTED"
    assert_batch_dimensions(env.read_batch(2025, 2), "VALIDATED", "UNSUBMITTED")
    assert_batch_dimensions(env.read_batch(2023, 1), "VALIDATED", "UNSUBMITTED")
