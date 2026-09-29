"""Conservation laws that must survive a compensating pair of moves."""

from test_helpers import (
    EPA_HEADERS,
    PM_HEADERS,
    QA_HEADERS,
    apply_invalidation,
    approved_assessment,
    assert_hour_budget_conserved,
    assert_pct,
    assert_site_census_partitioned,
    canonical_environment,
    data_batch_payload,
    find_by_id,
    get_success_data,
    set_clock,
    submitted_change_request,
    validate_paginated,
    validate_success,
)


def _quarter_with_an_excused_and_an_unexcused_range(api):
    env = canonical_environment(api)
    batch = get_success_data(
        api.create_data_batch(
            data_batch_payload(env.monitor_id, 2025, 3, scheduled_hour_count=2160), QA_HEADERS
        )
    )
    env.batches = [batch]
    unexcused = apply_invalidation(api, batch["id"], 0, 100, "QC_FAILURE")
    excused = apply_invalidation(api, batch["id"], 200, 260, "SCHEDULED_MAINTENANCE")
    return env, batch["id"], unexcused, excused


def test_the_hour_budget_is_conserved_while_both_ranges_are_applied(api):
    """Sixty excused hours leave the denominator; one hundred unexcused hours do not.

    PRD 2.9: "Across every recompute — an invalidation added, an invalidation withdrawn, an
    event exclusion made effective — the quarter's `scheduled_hour_count` always equals the
    sum of `valid_hour_count`, `invalidated_hour_count`, `excused_hour_count` and
    `event_excluded_hour_count`."

    Design: Difficulty/compensating_invariant/batch_hour_budget_conserved_across_invalidation_withdrawal
    """
    env, batch_id, _, _ = _quarter_with_an_excused_and_an_unexcused_range(api)

    batch = get_success_data(api.get_data_batch(batch_id, QA_HEADERS))
    assert batch["excused_hour_count"] == 60
    assert batch["invalidated_hour_count"] == 100
    assert batch["adjusted_scheduled_hour_count"] == 2100
    assert batch["valid_hour_count"] == 2000
    assert_pct(batch["completeness_pct"], 95.2)
    assert_hour_budget_conserved(batch)


def test_withdrawing_the_unexcused_range_restores_its_hours_and_keeps_the_budget(api):
    """The withdrawal returns one hundred hours to valid without touching the excused row.

    PRD 3.4: "The invalidation advances `APPLIED → WITHDRAWN`, `withdrawn_reason` is
    stored, the parent quarter re-runs hour accounting with the withdrawn hours restored to
    `valid_hour_count`"

    Design: Difficulty/compensating_invariant/batch_hour_budget_conserved_across_invalidation_withdrawal
    """
    env, batch_id, unexcused, excused = _quarter_with_an_excused_and_an_unexcused_range(api)

    validate_success(
        api.withdraw_invalidation(
            unexcused["id"],
            {"withdrawn_reason": "Re-review found the analyser within tolerance"},
            QA_HEADERS,
        )
    )

    rows, _ = validate_paginated(api.list_batch_invalidations(batch_id, QA_HEADERS))
    assert find_by_id(rows, unexcused["id"])["status"] == "WITHDRAWN"
    assert find_by_id(rows, excused["id"])["status"] == "APPLIED"

    batch = get_success_data(api.get_data_batch(batch_id, QA_HEADERS))
    assert batch["invalidated_hour_count"] == 0
    assert batch["excused_hour_count"] == 60
    assert batch["event_excluded_hour_count"] == 0
    assert batch["valid_hour_count"] == 2100
    assert_pct(batch["completeness_pct"], 100.0)
    assert batch["regulatory_use_eligible"] is True
    assert_hour_budget_conserved(batch)


def _suspended_site(api):
    env = canonical_environment(api)
    approved_assessment(env, cycle_year=2026)
    submitted_change_request(env, "SEASONAL_SUSPENSION")
    validate_success(
        api.decide_change_request(
            env.change_request_id,
            {"decision": "APPROVE", "decision_note": "Winter shutdown authorised"},
            EPA_HEADERS,
        )
    )
    return env


def test_the_site_census_is_conserved_while_the_site_sits_suspended(api):
    """Suspension moves the site between buckets without changing the total.

    PRD 3.9: "the network's `operating_site_count` decrements by 1 and its
    `suspended_site_count` increments by 1, with `total_site_count` unchanged."

    Design: Difficulty/compensating_invariant/network_site_census_conserved_across_suspension_and_reinstatement
    """
    env = _suspended_site(api)

    site = env.read_site()
    assert site["status"] == "SUSPENDED"
    assert site["suspended_at"].startswith("2026-01-05T00:00:00")

    monitor = env.read_monitor()
    assert monitor["monitor_status"] == "OUT_OF_SERVICE"
    assert monitor["out_of_service_since"].startswith("2026-01-05T00:00:00")

    network = env.read_network()
    assert network["total_site_count"] == 1
    assert network["operating_site_count"] == 0
    assert network["suspended_site_count"] == 1
    assert_site_census_partitioned(network)


def test_reinstatement_is_the_exact_inverse_and_closes_out_the_accrual(api):
    """Ten forgiven days later the census and both postures come back intact.

    PRD 3.9: "Each such instrument adds to `out_of_service_day_count` the whole days
    elapsed from its `out_of_service_since` to the logical clock and then clears
    `out_of_service_since`."

    Design: Difficulty/compensating_invariant/network_site_census_conserved_across_suspension_and_reinstatement
    """
    env = _suspended_site(api)
    set_clock(api, "2026-01-15T00:00:00Z")
    validate_success(
        api.reinstate_site(
            env.site_id, {"reinstatement_note": "Seasonal operations resumed"}, PM_HEADERS
        )
    )

    site = env.read_site()
    assert site["status"] == "OPERATING"
    assert site["suspended_at"] is None

    monitor = env.read_monitor()
    assert monitor["monitor_status"] == "OPERATING"
    assert monitor["out_of_service_since"] is None
    assert monitor["out_of_service_day_count"] == 10
    assert monitor["qc_posture"] == "QC_CURRENT"
    assert monitor["qc_posture_in_service"] == "QC_CURRENT"

    network = env.read_network()
    assert network["total_site_count"] == 1
    assert network["operating_site_count"] == 1
    assert network["suspended_site_count"] == 0
    assert_site_census_partitioned(network)

    request = get_success_data(api.get_change_request(env.change_request_id, PM_HEADERS))
    assert request["status"] == "APPROVED"
    assert request["request_type"] == "SEASONAL_SUSPENSION"
