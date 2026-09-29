"""The two recovery-time variants, the two recovery-point variants and the three axes."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    assert_achieved,
    assert_axes,
    assert_instant,
    assert_objectives,
    assert_reserved_capacity,
    factories as f,
    fixtures as fx,
)


def test_component_failover_is_measured_as_net_hands_on_time(api):
    """Only worked step executions count, and idle time between them is invisible.

    PRD: "For a `TABLETOP` or a `COMPONENT_FAILOVER` the measure is *net hands-on
    time*: add up the `elapsed_minutes` of every step execution of this exercise
    whose `outcome` is `PASSED`, `PASSED_WITH_ISSUE` or `FAILED`."

    Design: Difficulty/dual_variant_calc/rto_variant_wall_clock_vs_net_execution
    """
    estate = fx.setup_recovery_time_variant_scenario(api)
    coordinator = estate["coordinator_headers"]

    component = fx.read_exercise(api, coordinator, estate["component_exercise"]["id"])

    assert_axes(component, execution_state="FAILOVER_COMPLETE")
    assert_objectives(component, 45, 15)
    assert_achieved(component, achieved_rto_minutes=34, rto_met=True)
    # 34 is 13 plus 21; the skipped 10-minute row and the 80-minute wall-clock
    # span are both excluded from this variant.
    assert component["achieved_rto_minutes"] != 80


def test_full_site_failover_is_measured_as_the_elapsed_outage_window(api):
    """The same step rows over the same span are judged on wall-clock time instead.

    PRD: "For a `FULL_SITE_FAILOVER` the measure is the *elapsed outage window*:
    take the time from `execution_started_at` to `failover_completed_at` and
    round up to a whole minute."

    Design: Difficulty/dual_variant_calc/rto_variant_wall_clock_vs_net_execution
    """
    estate = fx.setup_recovery_time_variant_scenario(api)
    coordinator = estate["coordinator_headers"]

    fx.drive_execution(
        api, coordinator, estate["full_site_exercise"]["id"], "COMPLETE_FAILOVER"
    )

    full_site = fx.read_exercise(api, coordinator, estate["full_site_exercise"]["id"])
    assert_axes(full_site, execution_state="FAILOVER_COMPLETE")
    assert_objectives(full_site, 45, 15)
    assert_achieved(full_site, achieved_rto_minutes=80, rto_met=False)
    assert_instant(full_site["execution_started_at"], "2026-09-11T00:00:00Z")
    assert_instant(full_site["failover_completed_at"], "2026-09-11T01:20:00Z")


def test_replication_lag_variant_uses_the_worst_observed_lag(api):
    """With every in-scope store replicating continuously, lag decides the RPO.

    PRD: "Under replication lag, each data store yields its chosen observation's
    `replication_lag_seconds` converted to whole minutes by rounding up, and
    `achieved_rpo_minutes` is the largest of those per-asset figures."

    Design: Difficulty/dual_variant_calc/rpo_variant_replication_lag_vs_transaction_gap
    """
    estate = fx.setup_recovery_point_variant_scenario(api)
    coordinator = estate["coordinator_headers"]

    lag_exercise = fx.read_exercise(api, coordinator, estate["lag_exercise"]["id"])

    assert_axes(lag_exercise, execution_state="FAILOVER_COMPLETE")
    assert_objectives(lag_exercise, 45, 15)
    assert_achieved(lag_exercise, achieved_rpo_minutes=4, rpo_met=True)


def test_one_batch_snapshot_store_switches_the_whole_exercise_to_transaction_gap(api):
    """A single snapshot-replicated store changes the variant for every store.

    PRD: "If any in-scope data store runs `replication_mode` `BATCH_SNAPSHOT`,
    the whole exercise is measured by transaction gap; otherwise it is measured
    by replication lag."

    Design: Difficulty/dual_variant_calc/rpo_variant_replication_lag_vs_transaction_gap
    """
    estate = fx.setup_recovery_point_variant_scenario(api)
    coordinator = estate["coordinator_headers"]
    assert estate["asset_snapshot"]["replication_mode"] == "BATCH_SNAPSHOT"

    fx.drive_execution(api, coordinator, estate["gap_exercise"]["id"], "COMPLETE_FAILOVER")

    gap_exercise = fx.read_exercise(api, coordinator, estate["gap_exercise"]["id"])
    assert_axes(gap_exercise, execution_state="FAILOVER_COMPLETE")
    assert_achieved(gap_exercise, achieved_rpo_minutes=6, rpo_met=True)
    assert gap_exercise["achieved_rpo_minutes"] != 4


def test_data_axis_loop_leaves_the_other_two_axes_untouched(api):
    """Divergence and reconciliation move the data axis alone.

    PRD: "None of these transitions has any cross-entity effect:
    `execution_state` and `failback_state` are untouched, and the exercise stays
    at `FAILOVER_COMPLETE` throughout."

    Design: Difficulty/non_linear_state_machine/exercise_three_axes_advance_independently_then_join_at_close
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    operator = estate["operator_headers"]
    exercise = fx.setup_exercise_at_failover_complete(
        api,
        estate,
        name="Three-axis rehearsal",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )

    fx.drive_data(api, operator, exercise["id"], "BEGIN_VALIDATION")
    diverged = fx.drive_data(api, operator, exercise["id"], "FLAG_DIVERGENT")

    assert_axes(
        diverged,
        execution_state="FAILOVER_COMPLETE",
        data_state="DATA_DIVERGENT",
        failback_state="FAILBACK_NOT_PLANNED",
    )

    fx.drive_data(api, operator, exercise["id"], "RECONCILE")
    fx.drive_failback(api, operator, exercise["id"], "PLAN")
    fx.drive_failback(api, operator, exercise["id"], "START_SYNC")
    failed_sync = fx.drive_failback(api, operator, exercise["id"], "RECORD_SYNC_FAILURE")

    assert_axes(
        failed_sync,
        execution_state="FAILOVER_COMPLETE",
        data_state="DATA_RECONCILING",
        failback_state="SYNC_FAILED",
    )
    assert_axes(
        fx.read_exercise(api, coordinator, exercise["id"]), closure_reason="NONE"
    )


def test_closure_joins_the_three_axes_and_releases_the_reservation(api):
    """Closure is refused until both other axes are terminal, then releases capacity.

    PRD: "The coordinator closes the exercise, advancing `execution_state` from
    `FAILOVER_COMPLETE` to the terminal `CLOSED`, but only when `data_state` has
    reached `DATA_VERIFIED` **and** `failback_state` has reached
    `FAILBACK_COMPLETE`."

    Design: Difficulty/non_linear_state_machine/exercise_three_axes_advance_independently_then_join_at_close
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    operator = estate["operator_headers"]
    site_id = estate["site_recovery"]["id"]
    exercise = fx.setup_exercise_at_failover_complete(
        api,
        estate,
        name="Three-axis rehearsal",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 2)

    fx.drive_data(api, operator, exercise["id"], "BEGIN_VALIDATION")
    fx.drive_data(api, operator, exercise["id"], "FLAG_DIVERGENT")
    fx.drive_data(api, operator, exercise["id"], "RECONCILE")
    fx.drive_failback(api, operator, exercise["id"], "PLAN")
    fx.drive_failback(api, operator, exercise["id"], "START_SYNC")
    fx.drive_failback(api, operator, exercise["id"], "RECORD_SYNC_FAILURE")
    fx.drive_data(api, operator, exercise["id"], "REVALIDATE")
    fx.drive_data(api, operator, exercise["id"], "VERIFY")
    fx.drive_failback(api, operator, exercise["id"], "RETRY_SYNC")
    fx.drive_failback(api, operator, exercise["id"], "COMPLETE")
    closed = fx.drive_execution(api, coordinator, exercise["id"], "CLOSE")

    assert_axes(
        closed,
        execution_state="CLOSED",
        data_state="DATA_VERIFIED",
        failback_state="FAILBACK_COMPLETE",
        closure_reason="CLOSED_NORMALLY",
    )
    assert_achieved(closed, achieved_rto_minutes=13, achieved_rpo_minutes=4)
    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 0)


def test_start_without_an_agreed_application_in_scope_is_rejected(api):
    """An empty group offers nothing to measure against, so the start is refused.

    PRD: "At least one application whose `tier_agreement_status` is `AGREED` must
    be a member of an in-scope group, otherwise there is nothing to measure
    against and the request is rejected with `ERR_NO_RTO_BASELINE`."

    Design: Difficulty/boundary_precision_check/zero_agreed_applications_rejects_start_one_agreed_application_allows_it
    """
    estate = fx.setup_empty_group_baseline_scenario(api)
    coordinator = estate["coordinator_headers"]

    validate_error(
        api.transition_execution(
            estate["exercise"]["id"], f.execution_transition_payload("START"), coordinator
        ),
        ApiErrorId.ERR_NO_RTO_BASELINE,
        422,
    )

    blocked = fx.read_exercise(api, coordinator, estate["exercise"]["id"])
    assert_axes(blocked, execution_state="SCHEDULED")
    assert blocked["execution_started_at"] is None
    assert blocked["rto_objective_minutes"] is None
    assert blocked["rpo_objective_minutes"] is None
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_recovery"]["id"]), 2
    )


def test_one_agreed_application_pins_the_objectives_and_allows_the_start(api):
    """The single agreed member supplies both objectives.

    PRD: "Those baseline applications are exactly the `AGREED` members of the
    in-scope groups; `rto_objective_minutes` is the smallest `rto_minutes` among
    them and `rpo_objective_minutes` is the smallest `rpo_minutes` among them —
    the tightest promise made to any in-scope business owner becomes the whole
    exercise's target."

    Design: Difficulty/boundary_precision_check/zero_agreed_applications_rejects_start_one_agreed_application_allows_it
    """
    estate = fx.setup_empty_group_baseline_scenario(api)
    coordinator = estate["coordinator_headers"]
    fx.assign_application(
        api, coordinator, estate["solo_application"]["id"], estate["group"]["id"]
    )

    started = fx.drive_execution(api, coordinator, estate["exercise"]["id"], "START")

    assert_axes(started, execution_state="IN_EXECUTION")
    assert_objectives(started, 45, 60)


def test_evidence_submission_before_closure_is_rejected(api):
    """A package cannot be submitted while its exercise is still running.

    PRD: "`SUBMIT`, taken by an `AuditLiaison`, moves `DRAFT` to `SUBMITTED` and
    requires the evidenced exercise's `execution_state` to be `CLOSED`;
    submitting against an exercise that is still running, or that was cancelled
    or aborted, is rejected with `ERR_EXERCISE_NOT_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/evidence_submission_depends_on_exercise_closed
    """
    estate = fx.setup_evidence_scenario(api)

    validate_error(
        api.transition_evidence_package(
            estate["package"]["id"],
            f.evidence_transition_payload("SUBMIT"),
            estate["liaison_headers"],
        ),
        ApiErrorId.ERR_EXERCISE_NOT_CLOSED,
        422,
    )

    package = fx.read_evidence_package(
        api, estate["liaison_headers"], estate["package"]["id"]
    )
    assert package["state"] == "DRAFT"
    assert package["manifest_line_count"] == 0


def test_manifest_is_counted_once_the_exercise_is_closed(api):
    """With the exercise closed the submission lands and counts the manifest.

    PRD: "Submission computes `manifest_line_count`: one header line, plus one
    line for each scope item of the evidenced exercise, plus one line for each
    step execution of that exercise regardless of its `outcome`, plus one line
    for each finding raised against that exercise whose `state` is anything other
    than `WITHDRAWN`."

    Design: Difficulty/cross_entity_state_dependency/evidence_submission_depends_on_exercise_closed
    """
    estate = fx.setup_evidence_scenario(api)
    coordinator = estate["coordinator_headers"]
    exercise_id = estate["exercise"]["id"]
    fx.drive_both_axes_to_terminal(api, estate["operator_headers"], exercise_id)
    fx.drive_execution(api, coordinator, exercise_id, "CLOSE")

    submitted = fx.transition_evidence(
        api, estate["liaison_headers"], estate["package"]["id"], "SUBMIT"
    )

    assert submitted["state"] == "SUBMITTED"
    assert submitted["manifest_line_count"] == 3
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_recovery"]["id"]), 0
    )
