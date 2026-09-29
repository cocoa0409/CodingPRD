"""
Failure handling and currency: the alert-only charge on a failed run, the retry
cycle, the three-failure suspension cascade, and the grace boundaries the portal
sweep ages a published dataset through.
"""

from test_helpers import (
    PORTAL_ADMIN_HEADERS,
    assert_credit_buckets,
    assert_dataset_states,
    assert_money,
    assert_posture,
    assert_priority,
    assert_settlement,
    fixtures,
    validate_success,
)

SLOT = "2026-08-01T09:00:00Z"
RETRY_SLOT = "2026-08-01T09:30:00Z"

HIGH_VALUE_EPOCH = [
    {"epoch_index": 1, "api_call_count": 20000, "download_count": 5000},
]


def test_failed_run_settles_an_alert_only_charge_and_keeps_the_pipeline_armed(api):
    """One failure charges 3 credits for the alert and nothing for compute.

    The PRD: "Reporting failure moves the run `RUNNING → FAILED` and takes a
    `failure_code` of `SOURCE_UNAVAILABLE`, `SCHEMA_DRIFT`, `TIMEOUT` or
    `TRANSFORM_ERROR`." and "Hop one records the outcome: `failure_code` is stored,
    `alert_dispatched` is set to true and an alert is dispatched to the pipeline's
    `alert_email`, `rows_ingested` stays 0, the pipeline's `consecutive_failure_count`
    increases by 1 and that new value is copied into the run's
    `consecutive_failure_index`, and the alert-only charge is settled through the same
    waterfall."

    With no rows ingested `compute_credits` is 0.00 and only "Step two computes
    `alert_credits`: 3 credits when `alert_dispatched` is true, and 0.00 when it is
    false." applies, so the subtotal of 3.00 sits below every discount tier and settles
    at 3.00. A single failure does not reach the streak limit, so the pipeline stays
    `ARMED` and the dataset stays `CURRENT`.

    Design: Difficulty/non_linear_state_machine/pipeline_run_failed_requeue_started_cycle
    """
    ctx = fixtures.setup_running_run(api=api)

    run = fixtures.report_failure(ctx["run_id"], failure_code="TIMEOUT", api=api)

    assert run["status"] == "FAILED", f"Expected FAILED, got {run['status']}"
    assert run["failure_code"] == "TIMEOUT", (
        f"Expected failure_code TIMEOUT, got {run['failure_code']}"
    )
    assert run["alert_dispatched"] is True, (
        f"A failure must dispatch an alert, got {run['alert_dispatched']!r}"
    )
    assert run["rows_ingested"] == 0, f"Expected rows_ingested 0, got {run['rows_ingested']}"
    assert_settlement(
        run,
        compute_credits=0.00,
        alert_credits=3.00,
        subtotal_credits=3.00,
        reliability_discount_pct=0.00,
        total_charge_credits=3.00,
    )

    pipeline = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert pipeline["status"] == "ARMED", (
        f"One failure must not suspend the pipeline, got {pipeline['status']}"
    )
    assert pipeline["consecutive_failure_count"] == 1, (
        f"Expected consecutive_failure_count 1, got {pipeline['consecutive_failure_count']}"
    )
    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, currency_status="CURRENT")
    assert dataset["staleness_alert_count"] == 0, (
        f"A failure alert must not raise staleness_alert_count, "
        f"got {dataset['staleness_alert_count']}"
    )


def test_requeued_run_clears_its_stamps_and_the_retry_rolls_the_dataset_forward(api):
    """Requeueing rewinds the run so the retry can settle as a fresh success.

    The PRD: "The transition `FAILED → RETRY_QUEUED` takes a replacement
    `scheduled_for_utc`, requires the pipeline to still be `ARMED`, requires that instant
    to be at or after the logical clock and its minute-of-day to fall inside the
    pipeline's half-open window, and then overwrites `scheduled_for_utc`, clears
    `failure_code`, `started_at` and `finished_at`, and sets `alert_dispatched` back to
    false."

    The retry then ingests 45000 rows for a 20.00 subtotal and a 19.00 charge, and "The
    pipeline's `consecutive_failure_count` resets to 0." Across the failed 3.00 and the
    successful 19.00 the department has consumed 22.00, drawing the whole 10.00 escrow
    and 12.00 of balance.

    Design: Difficulty/non_linear_state_machine/pipeline_run_failed_requeue_started_cycle
    """
    ctx = fixtures.setup_running_run(api=api)
    fixtures.report_failure(ctx["run_id"], failure_code="TIMEOUT", api=api)

    requeued = fixtures.requeue_run(ctx["run_id"], RETRY_SLOT, api=api)
    assert requeued["status"] == "RETRY_QUEUED", (
        f"Expected RETRY_QUEUED, got {requeued['status']}"
    )
    assert requeued["started_at"] is None, (
        f"Requeueing must clear started_at, got {requeued['started_at']!r}"
    )
    assert requeued["finished_at"] is None, (
        f"Requeueing must clear finished_at, got {requeued['finished_at']!r}"
    )
    assert requeued["failure_code"] is None, (
        f"Requeueing must clear failure_code, got {requeued['failure_code']!r}"
    )
    assert requeued["alert_dispatched"] is False, (
        f"Requeueing must reset alert_dispatched, got {requeued['alert_dispatched']!r}"
    )

    fixtures.set_clock(RETRY_SLOT, api=api)
    running = fixtures.start_run(ctx["run_id"], api=api)
    assert running["status"] == "RUNNING", f"Expected RUNNING, got {running['status']}"

    settled = fixtures.report_success(ctx["run_id"], 45000, api=api)
    assert_settlement(
        settled,
        subtotal_credits=20.00,
        reliability_discount_pct=0.05,
        total_charge_credits=19.00,
    )

    pipeline = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert pipeline["consecutive_failure_count"] == 0, (
        f"A success must reset the streak, got {pipeline['consecutive_failure_count']}"
    )
    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(
        department, issued=100.00, balance=78.00, escrowed=0.00, consumed=22.00
    )
    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert dataset["live_row_count"] == 45000, (
        f"Expected live_row_count 45000, got {dataset['live_row_count']}"
    )
    assert dataset["version_index_high_water"] == 2, (
        f"Expected version_index_high_water 2, got {dataset['version_index_high_water']}"
    )
    assert_dataset_states(dataset, currency_status="CURRENT")


def _pipeline_with_four_runs(api):
    """An armed pipeline whose window holds four runs, the first already started."""
    ctx = fixtures.setup_running_run(api=api)
    ctx["extra_runs"] = [
        fixtures.schedule_run(ctx["pipeline_id"], SLOT, api=api)["id"] for _ in range(3)
    ]
    return ctx


def test_two_consecutive_failures_stay_below_the_streak_limit(api):
    """The suspension cascade fires on the third failure, not the second.

    The PRD: "Hop two fires when `consecutive_failure_count` has reached 3: the pipeline
    transitions `ARMED → SUSPENDED` with `suspend_reason` `FAILURE_STREAK`, which skips
    its pending runs as described in §3.5." Two failures leave the count at 2, so the
    pipeline keeps its window and the dataset keeps its freshness.

    Design: Difficulty/transitive_cascade/run_failure_streak_suspension_three_hop_chain
    """
    ctx = _pipeline_with_four_runs(api)

    fixtures.report_failure(ctx["run_id"], failure_code="SOURCE_UNAVAILABLE", api=api)
    after_one = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert after_one["consecutive_failure_count"] == 1, (
        f"Expected consecutive_failure_count 1, got {after_one['consecutive_failure_count']}"
    )
    assert after_one["status"] == "ARMED", f"Expected ARMED, got {after_one['status']}"

    second = ctx["extra_runs"][0]
    fixtures.start_run(second, api=api)
    fixtures.report_failure(second, failure_code="SCHEMA_DRIFT", api=api)

    after_two = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert after_two["consecutive_failure_count"] == 2, (
        f"Expected consecutive_failure_count 2, got {after_two['consecutive_failure_count']}"
    )
    assert after_two["status"] == "ARMED", f"Expected ARMED, got {after_two['status']}"
    assert after_two["suspend_reason"] is None, (
        f"Expected no suspend_reason, got {after_two['suspend_reason']!r}"
    )
    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, currency_status="CURRENT")


def test_third_failure_suspends_the_pipeline_skips_pending_runs_and_stales_the_dataset(api):
    """The third failure cascades through the pipeline, the runs, the dataset and the department.

    The PRD chains three consequences off the streak. Hop two suspends the pipeline;
    suspension "skips its pending runs as described in §3.5", where a skipped run has
    "`skip_reason` set to `PIPELINE_SUSPENDED` when the pipeline was suspended". Hop
    three: "Hop three follows from the pipeline having become suspended: the dataset's
    `currency_status` takes the `STALE` floor — formally, the dataset's currency becomes
    the more severe of what the clock alone would say and `STALE`, so a dataset that was
    perfectly fresh moves `CURRENT → STALE` in one step, skipping `AGING` entirely — and
    its `staleness_alert_count` increases by 1". Hop four re-derives the department,
    where "`risk_points` is then three points for each breached dataset, plus two points
    for each stale dataset, plus two points for each dataset under remediation, plus one
    point for each overdue correction." — two points here, and "From `risk_points` the
    posture follows on inclusive boundaries: at least 6 points is `SUSPENDED`, from 2
    through 5 points is `RESTRICTED`, and 1 point or 0 points is `OPEN`."

    Suspension keeps the money: three alert-only charges of 3.00 have been consumed out
    of the 10.00 escrow, leaving 1.00 still reserved, and the runner gives the window's
    count back.

    Design: Difficulty/transitive_cascade/run_failure_streak_suspension_three_hop_chain
    """
    ctx = _pipeline_with_four_runs(api)
    second, third, fourth = ctx["extra_runs"]

    fixtures.report_failure(ctx["run_id"], failure_code="SOURCE_UNAVAILABLE", api=api)
    fixtures.start_run(second, api=api)
    fixtures.report_failure(second, failure_code="SCHEMA_DRIFT", api=api)
    fixtures.start_run(third, api=api)
    failed = fixtures.report_failure(third, failure_code="TRANSFORM_ERROR", api=api)
    assert_settlement(failed, subtotal_credits=3.00, total_charge_credits=3.00)

    pipeline = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert pipeline["status"] == "SUSPENDED", f"Expected SUSPENDED, got {pipeline['status']}"
    assert pipeline["suspend_reason"] == "FAILURE_STREAK", (
        f"Expected suspend_reason FAILURE_STREAK, got {pipeline['suspend_reason']}"
    )
    assert pipeline["consecutive_failure_count"] == 3, (
        f"Expected consecutive_failure_count 3, got {pipeline['consecutive_failure_count']}"
    )

    skipped = fixtures.read_run(fourth, api=api)
    assert skipped["status"] == "SKIPPED", f"Expected SKIPPED, got {skipped['status']}"
    assert skipped["skip_reason"] == "PIPELINE_SUSPENDED", (
        f"Expected skip_reason PIPELINE_SUSPENDED, got {skipped['skip_reason']}"
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="PUBLISHED", currency_status="STALE")
    assert dataset["staleness_alert_count"] == 1, (
        f"Expected staleness_alert_count 1, got {dataset['staleness_alert_count']}"
    )

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_posture(department, stale=1, risk_points=2, compliance_posture="RESTRICTED")
    assert_credit_buckets(
        department, issued=100.00, balance=90.00, escrowed=1.00, consumed=9.00
    )
    runner = validate_success(api.get_ingest_runner(ctx["runner_id"], PORTAL_ADMIN_HEADERS))
    assert runner["armed_window_count"] == 0, (
        f"Suspension must release the runner's window count, "
        f"got {runner['armed_window_count']}"
    )


def _committed_high_value_dataset(api):
    """A published TIER_1 dataset committed to the high-value service level."""
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    dataset = fixtures.report_usage_epochs(ctx["dataset_id"], HIGH_VALUE_EPOCH, api=api)
    assert_priority(dataset, priority_score=78.60, priority_tier="TIER_1")
    ctx["dataset"] = fixtures.commit_high_value(ctx["dataset_id"], api=api)
    return ctx


def test_high_value_dataset_is_still_aging_at_exactly_its_grace_allowance(api):
    """Two days overdue on a two-day grace is `AGING`, and `AGING` emits no alert.

    The PRD reads the allowance off the tier: "Third, a grace allowance is read off the
    dataset's `priority_tier`: 2 days for `TIER_1`, 7 days for `TIER_2`, 14 days for
    `TIER_3` — the more valuable the dataset, the shorter its rope." A single busy epoch
    caps engagement at 100.00 and lifts the score to 78.60, so this dataset is `TIER_1`
    and its rope is two days — which it also needs to be, since "The programme office
    commits a dataset to the high-value currency service level, which requires the
    dataset's `priority_tier` to be `TIER_1` and its `publication_status` to be `READY`
    or `PUBLISHED`; anything else is refused with `ERR_NOT_HIGH_VALUE_ELIGIBLE`."

    Published weekly on 2026-08-01, it falls due on 2026-08-08, so a sweep on 2026-08-10
    finds it two days overdue: "It is `AGING` when `days_overdue` is greater than zero
    but no greater than the grace allowance; the boundary is inclusive, so a
    `days_overdue` exactly equal to the grace is still `AGING` and one day beyond it is
    `STALE`." and "A dataset that merely became `AGING` emits nothing."

    Design: Difficulty/boundary_precision_check/currency_aging_stale_breached_grace_boundaries
    """
    ctx = _committed_high_value_dataset(api)
    assert ctx["dataset"]["high_value_committed"] is True, (
        f"Expected high_value_committed true, got {ctx['dataset']['high_value_committed']!r}"
    )
    assert str(ctx["dataset"]["next_due_at"]).startswith("2026-08-08T00:00:00"), (
        f"Expected next_due_at 2026-08-08T00:00:00Z, got {ctx['dataset']['next_due_at']!r}"
    )

    fixtures.advance_clock_and_sweep("2026-08-10T00:00:00Z", api=api)

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert dataset["days_overdue"] == 2, (
        f"Expected days_overdue 2, got {dataset['days_overdue']}"
    )
    assert_dataset_states(dataset, currency_status="AGING")
    assert dataset["staleness_alert_count"] == 0, (
        f"An AGING dataset must emit no alert, got {dataset['staleness_alert_count']}"
    )
    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_posture(
        department, stale=0, breached=0, risk_points=0, compliance_posture="OPEN"
    )


def test_one_day_past_the_grace_is_stale_and_beyond_twice_the_grace_is_breached(api):
    """Each sweep past the boundary escalates the currency and emits exactly one alert.

    The PRD: "It is `STALE` when `days_overdue` exceeds the grace but does not exceed
    twice the grace." and "Beyond twice the grace it is `BREACHED` — but only for a
    dataset whose `high_value_committed` flag is true; ". Alerting is per sweep: "Step
    two emits staleness alerting: every dataset that is entering or remaining in `STALE`
    or `BREACHED` emits exactly one alert per sweep, increasing `staleness_alert_count`
    by 1 and setting `last_staleness_alert_at` to the current logical instant."

    On a two-day grace, three days overdue is `STALE` — two risk points, so the
    department is `RESTRICTED` — and five days overdue is past twice the grace and
    `BREACHED`, which the PRD prices higher: three points for the breach, and the dataset
    is no longer counted as merely stale.

    Design: Difficulty/boundary_precision_check/currency_aging_stale_breached_grace_boundaries
    """
    ctx = _committed_high_value_dataset(api)
    fixtures.advance_clock_and_sweep("2026-08-10T00:00:00Z", api=api)

    fixtures.advance_clock_and_sweep("2026-08-11T00:00:00Z", api=api)
    stale = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert stale["days_overdue"] == 3, f"Expected days_overdue 3, got {stale['days_overdue']}"
    assert_dataset_states(stale, currency_status="STALE")
    assert stale["staleness_alert_count"] == 1, (
        f"Expected exactly one alert on entering STALE, got {stale['staleness_alert_count']}"
    )
    assert str(stale["last_staleness_alert_at"]).startswith("2026-08-11T00:00:00"), (
        f"Expected last_staleness_alert_at 2026-08-11T00:00:00Z, "
        f"got {stale['last_staleness_alert_at']!r}"
    )
    stale_department = fixtures.read_department(ctx["department_id"], api=api)
    assert_posture(
        stale_department,
        stale=1,
        breached=0,
        risk_points=2,
        compliance_posture="RESTRICTED",
    )

    fixtures.advance_clock_and_sweep("2026-08-13T00:00:00Z", api=api)
    breached = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert breached["days_overdue"] == 5, (
        f"Expected days_overdue 5, got {breached['days_overdue']}"
    )
    assert_dataset_states(breached, currency_status="BREACHED")
    assert breached["staleness_alert_count"] == 2, (
        f"Expected a second alert on the breaching sweep, "
        f"got {breached['staleness_alert_count']}"
    )
    breached_department = fixtures.read_department(ctx["department_id"], api=api)
    assert_posture(
        breached_department,
        breached=1,
        stale=0,
        risk_points=3,
        compliance_posture="RESTRICTED",
    )
    assert_money(breached_department["credits_issued_units"], 0.00, "credits_issued_units")
