"""Endpoints whose answer is computed at read time or swept in one batch pass."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    assert_allocated_traffic,
    assert_deltas_sum_to,
    assert_deployment_state,
    assert_drift_outcome,
    assert_health_score,
    assert_ledger_reasons,
    assert_pct,
    assert_ramp_step_row,
    assert_sweep_counters,
    assert_urgency_snapshot,
    assert_version_state,
)
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_MANUAL_OVERRIDE_ACTIVE,
    ERR_MODEL_ARCHIVED,
    ERR_OVERRIDE_EXCEEDS_CURRENT_TRAFFIC,
    ERR_RETRAINED_VERSION_LINEAGE_INVALID,
    ERR_STALE_MODEL_VERSION,
)
from test_helpers.constants import FLAT_BIN_PROPORTIONS
from test_helpers.factories import (
    build_evaluation_payload,
    build_incident_action_payload,
    build_model_version_payload,
    build_trigger_disposition_payload,
)
from test_helpers.fixtures import (
    approve_version,
    build_evaluation_arms,
    build_stack,
    close_window,
    create_approved_version,
    create_drift_report,
    create_incident,
    incident_action,
    ledger_rows,
    only_trigger,
    ramp,
    read_model_version_token,
    record_window,
    register_version,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN_1,
    APPROVER_1,
    MLE_1,
    RELIABILITY_1,
    USER_MLE_1,
)

_DRIFTED_BINS = [0.10, 0.15, 0.20, 0.25, 0.30]


def _open_triggers(api: ApiClient, model_id: str) -> int:
    return get_success_data(api.get_model(model_id, MLE_1))[
        "open_retraining_trigger_count"
    ]


def _disposition(api: ApiClient, trigger_id: str, action: str, **body) -> dict:
    return get_success_data(
        api.disposition_retraining_trigger(
            trigger_id, build_trigger_disposition_payload(action, **body), MLE_1
        )
    )


def _warn_breach(api: ApiClient, stack, closed_at: str) -> dict:
    """Score one closed distribution window against a flat training baseline."""
    window = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_kind="DISTRIBUTION",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T06:00:00Z",
        observed_bin_proportions=list(_DRIFTED_BINS),
    )
    set_clock(api, closed_at)
    close_window(api, window["id"])
    report = create_drift_report(api, window["id"], MLE_1)
    assert_drift_outcome(
        report, drift_index=0.1354, severity="WARN", status="BREACHED"
    )
    assert report["model_version_id"] == stack.version_id
    return report


# ─── One batch endpoint reporting four counters over two passes ───


def test_the_sweep_reports_what_it_created_skipped_and_staled(api):
    """The same sweep raises revalidation work and expires stale triggers.

    PRD 3.9: the sweep "selects every artifact version whose `approval_state` is
    `APPROVED`, whose `revalidation_due_at` is non-null and at or before the logical
    clock's present value, and which has no existing task in `status` `DUE` or
    `IN_REVIEW`", creating each task "with `due_at` copied from the version's
    `revalidation_due_at` as it stood at sweep time, and `swept_at` stamped from the
    clock"; "a second call at the same clock value reports a `created_count` of 0 and
    counts the same versions under `skipped_existing_count`". The same pass runs the
    trigger staleness pass: "every retraining trigger whose `status` is
    `ACKNOWLEDGED` or `IN_PROGRESS` and whose `stale_after` is at or before the
    logical clock's present value moves to `STALE` ... A trigger whose `stale_after`
    falls exactly on the clock is staled."

    Design: Corner/endpoints/revalidation_sweep_reports_created_skipped_and_staled_counts
    """
    stack = build_stack(api, ramps=1)
    assert_version_state(stack.version, revalidation_due_at="2026-10-30T00:00:00Z")

    _warn_breach(api, stack, "2026-08-02T00:00:00Z")
    later = create_approved_version(
        api,
        stack.model_id,
        stack.dataset_id,
        MLE_1,
        APPROVER_1,
        semver="1.0.1",
        artifact_digest="sha256:bbb",
    )
    assert_version_state(
        later, approval_state="APPROVED", revalidation_due_at="2026-10-31T00:00:00Z"
    )

    trigger = only_trigger(api, stack.model_id)
    acknowledged = _disposition(api, trigger["id"], "ACKNOWLEDGE")
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert_urgency_snapshot(acknowledged, stale_after="2026-10-31T00:00:00Z")
    assert _open_triggers(api, stack.model_id) == 1

    set_clock(api, "2026-10-30T00:00:00Z")
    first = get_success_data(api.run_revalidation_sweep(ADMIN_1))
    assert_sweep_counters(
        first, created_count=1, skipped_existing_count=0, staled_trigger_count=0
    )

    tasks, meta = validate_paginated(api.list_revalidation_tasks(APPROVER_1))
    assert meta["total_count"] == 1
    task = tasks[0]
    assert task["model_version_id"] == stack.version_id
    assert task["status"] == "DUE"
    assert task["due_at"] == "2026-10-30T00:00:00Z"
    assert task["swept_at"] == "2026-10-30T00:00:00Z"
    assert task["reviewer_user_id"] is None

    replayed = get_success_data(api.run_revalidation_sweep(ADMIN_1))
    assert_sweep_counters(
        replayed, created_count=0, skipped_existing_count=1, staled_trigger_count=0
    )
    assert _open_triggers(api, stack.model_id) == 1

    set_clock(api, "2026-10-31T00:00:00Z")
    third = get_success_data(api.run_revalidation_sweep(ADMIN_1))
    assert_sweep_counters(
        third,
        evaluated_count=2,
        created_count=1,
        skipped_existing_count=1,
        staled_trigger_count=1,
    )

    raised, later_meta = validate_paginated(
        api.list_revalidation_tasks(APPROVER_1, {"model_version_id": later["id"]})
    )
    assert later_meta["total_count"] == 1
    assert raised[0]["status"] == "DUE"
    assert raised[0]["due_at"] == "2026-10-31T00:00:00Z"
    assert raised[0]["swept_at"] == "2026-10-31T00:00:00Z"

    staled = get_success_data(api.get_retraining_trigger(trigger["id"], MLE_1))
    assert staled["status"] == "STALE"
    assert _open_triggers(api, stack.model_id) == 0


# ─── One read endpoint choosing both a window and an arithmetic ───


def _health(api: ApiClient, deployment_id: str, variant: str = None) -> dict:
    params = None if variant is None else {"score_variant": variant}
    return get_success_data(
        api.get_deployment_health(deployment_id, RELIABILITY_1, params)
    )


def test_the_health_read_picks_the_variant_and_the_latest_performance_window(api):
    """Four reads over the same deployment, and each one recomputes its answer.

    PRD 3.5: the health read "selects the deployment's most recent `PERFORMANCE`
    window ordered by `window_end` descending then `created_at` descending, and
    returns a small object carrying `deployment_id`, the deployment's current
    `health_state`, the `score_variant` it evaluated, the resulting `health_score`,
    the `baseline_delta_pct`, the `monitoring_window_id` it read, and that window's
    `prediction_count` and `labeled_prediction_count`", the variant parameter
    "defaults to `PROVISIONAL` when omitted", "asking for the `FINAL` variant over a
    window that is still `OPEN` computes the score on demand and **does not** persist
    it", and "when the deployment has no `PERFORMANCE` window at all, both
    `health_score` and `monitoring_window_id` come back null".

    Design: Corner/endpoints/deployment_health_read_selects_the_variant_and_the_latest_performance_window
    """
    stack = build_stack(api, ramps=1)

    empty = _health(api, stack.deployment_id)
    assert empty["deployment_id"] == stack.deployment_id
    assert empty["health_state"] == "HEALTHY"
    assert empty["score_variant"] == "PROVISIONAL"
    assert empty["health_score"] is None
    assert empty["monitoring_window_id"] is None

    first = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_kind="PERFORMANCE",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
        prediction_count=4000,
        labeled_prediction_count=1000,
        correct_labeled_count=880,
        positive_rate=0.34,
        p95_latency_ms=250,
        observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
    )
    assert first["status"] == "OPEN"
    assert_health_score(
        first, health_score=83.60, variant="PROVISIONAL", baseline_delta_pct=1.60
    )

    provisional = _health(api, stack.deployment_id)
    assert_health_score(
        provisional,
        health_score=83.60,
        variant="PROVISIONAL",
        baseline_delta_pct=1.60,
    )
    assert provisional["monitoring_window_id"] == first["id"]
    assert provisional["prediction_count"] == 4000
    assert provisional["labeled_prediction_count"] == 1000

    on_demand = _health(api, stack.deployment_id, "FINAL")
    assert_health_score(
        on_demand, health_score=74.15, variant="FINAL", baseline_delta_pct=-7.85
    )
    assert on_demand["monitoring_window_id"] == first["id"]

    unpersisted = get_success_data(
        api.get_monitoring_window(first["id"], RELIABILITY_1)
    )
    assert unpersisted["status"] == "OPEN"
    assert_health_score(
        unpersisted, health_score=83.60, variant="PROVISIONAL", baseline_delta_pct=1.60
    )

    set_clock(api, "2026-08-03T00:00:00Z")
    closed = close_window(api, first["id"])
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] == "2026-08-03T00:00:00Z"
    assert_health_score(
        closed, health_score=74.15, variant="FINAL", baseline_delta_pct=-7.85
    )
    deployment = get_success_data(
        api.get_deployment(stack.deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(deployment, health_state="HEALTHY", traffic_pct=5.00)
    assert_pct(deployment["health_score_final"], 74.15, "health_score_final")

    second = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_kind="PERFORMANCE",
        window_start="2026-08-02T01:00:00Z",
        window_end="2026-08-03T00:00:00Z",
        prediction_count=2000,
        labeled_prediction_count=2000,
        correct_labeled_count=1900,
        positive_rate=0.30,
        p95_latency_ms=200,
        observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
    )
    assert_health_score(
        second, health_score=97.75, variant="PROVISIONAL", baseline_delta_pct=15.75
    )

    decoy = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_kind="DISTRIBUTION",
        window_start="2026-08-02T01:00:00Z",
        window_end="2026-08-03T00:00:00Z",
        prediction_count=100,
        labeled_prediction_count=0,
        correct_labeled_count=0,
        positive_rate=0.30,
        p95_latency_ms=200,
        observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
    )
    assert decoy["window_kind"] == "DISTRIBUTION"

    latest = _health(api, stack.deployment_id)
    assert latest["monitoring_window_id"] == second["id"]
    assert_health_score(
        latest, health_score=97.75, variant="PROVISIONAL", baseline_delta_pct=15.75
    )
    assert latest["prediction_count"] == 2000
    assert latest["labeled_prediction_count"] == 2000

    latest_final = _health(api, stack.deployment_id, "FINAL")
    assert latest_final["monitoring_window_id"] == second["id"]
    assert_health_score(
        latest_final, health_score=97.75, variant="FINAL", baseline_delta_pct=15.75
    )


# ─── One action endpoint that pins traffic and one that hands it back ───


def test_a_manual_override_pins_traffic_blocks_the_ramp_and_is_compensated(api):
    """The override displaces traffic, freezes the planner, and is released intact.

    PRD 3.8: MANUAL_OVERRIDE requires `override_traffic_pct` "at least 0.00 and
    strictly less than the deployment's current `traffic_pct`, or the request is
    rejected with `ERR_OVERRIDE_EXCEEDS_CURRENT_TRAFFIC`", then pins `traffic_pct` and
    appends a `MANUAL_OVERRIDE` row whose `delta_pct` is "the override minus that
    pre-call value". RESOLVE restores `traffic_pct` "to the `from_traffic_pct` of the
    most recent ramp-ledger row for this deployment whose `reason` is
    `MANUAL_OVERRIDE`" and appends an `OVERRIDE_RELEASE` row that is "the exact
    negation of the override row's delta". PRD 3.4 has the ramp reject while
    "`manual_override_active` must be false, rejecting with
    `ERR_MANUAL_OVERRIDE_ACTIVE`", which PRD 2.7 places in the state band ahead of the
    safety band's open-incident block.

    Design: Corner/endpoints/manual_override_pins_traffic_blocks_ramp_and_is_compensated_on_resolve
    """
    stack = build_stack(api, ramps=2)
    incident = create_incident(api, stack.deployment_id)
    assert incident["status"] == "OPEN"

    not_an_intervention = api.incident_action(
        incident["id"],
        build_incident_action_payload("MANUAL_OVERRIDE", override_traffic_pct=15.00),
        RELIABILITY_1,
    )
    validate_error(not_an_intervention, ERR_OVERRIDE_EXCEEDS_CURRENT_TRAFFIC)
    assert (
        get_success_data(api.get_prediction_incident(incident["id"], RELIABILITY_1))[
            "status"
        ]
        == "OPEN"
    )

    overridden = incident_action(
        api, incident["id"], "MANUAL_OVERRIDE", override_traffic_pct=5.00
    )
    assert overridden["status"] == "MITIGATING"
    assert_pct(
        overridden["manual_override_traffic_pct"], 5.00, "manual_override_traffic_pct"
    )

    pinned = get_success_data(api.get_deployment(stack.deployment_id, RELIABILITY_1))
    assert_deployment_state(
        pinned,
        rollout_state="RAMPING",
        traffic_pct=5.00,
        ramp_step_index=2,
        cumulative_ramp_delta_pct=5.00,
        manual_override_active=True,
    )
    assert_pct(pinned["override_traffic_pct"], 5.00, "override_traffic_pct")
    assert_allocated_traffic(
        get_success_data(api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)),
        5.00,
    )

    surrendered = ledger_rows(api, stack.deployment_id)
    assert_ledger_reasons(surrendered, ["RAMP_STEP", "RAMP_STEP", "MANUAL_OVERRIDE"])
    assert_ramp_step_row(
        surrendered[-1],
        from_traffic_pct=15.00,
        to_traffic_pct=5.00,
        delta_pct=-10.00,
        reason="MANUAL_OVERRIDE",
    )

    validate_error(
        api.ramp_deployment(stack.deployment_id, RELIABILITY_1),
        ERR_MANUAL_OVERRIDE_ACTIVE,
        409,
    )
    assert_deployment_state(
        get_success_data(api.get_deployment(stack.deployment_id, RELIABILITY_1)),
        traffic_pct=5.00,
        ramp_step_index=2,
    )

    assert incident_action(api, incident["id"], "MONITOR")["status"] == "MONITORING"
    set_clock(api, "2026-08-02T00:00:00Z")
    resolved = incident_action(api, incident["id"], "RESOLVE")
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_at"] == "2026-08-02T00:00:00Z"

    restored = get_success_data(api.get_deployment(stack.deployment_id, RELIABILITY_1))
    assert_deployment_state(
        restored,
        rollout_state="RAMPING",
        traffic_pct=15.00,
        ramp_step_index=2,
        cumulative_ramp_delta_pct=15.00,
        manual_override_active=False,
    )
    assert restored["override_traffic_pct"] is None
    assert_allocated_traffic(
        get_success_data(api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)),
        15.00,
    )

    compensated = ledger_rows(api, stack.deployment_id)
    assert_ledger_reasons(
        compensated,
        ["RAMP_STEP", "RAMP_STEP", "MANUAL_OVERRIDE", "OVERRIDE_RELEASE"],
    )
    assert_ramp_step_row(
        compensated[-1],
        from_traffic_pct=5.00,
        to_traffic_pct=15.00,
        delta_pct=10.00,
        reason="OVERRIDE_RELEASE",
    )
    assert_deltas_sum_to(compensated, 15.00)

    released = ramp(api, stack.deployment_id)
    assert_deployment_state(
        released,
        rollout_state="RAMPING",
        traffic_pct=35.00,
        ramp_step_index=3,
        cumulative_ramp_delta_pct=35.00,
    )


# ─── One disposition endpoint whose landing state is read off another row ───


def test_linking_a_retrained_version_lands_on_in_progress_then_satisfied(api):
    """The same action, the same version, two destinations decided by approval.

    PRD 3.6: LINK_VERSION requires the linked version's "`model_id` [to] equal the
    trigger's `model_id`, and its `parent_version_id` [to] be the drift report's
    `model_version_id`", rejecting either lineage failure with
    `ERR_RETRAINED_VERSION_LINEAGE_INVALID`. "From `ACKNOWLEDGED` the action **forks on
    the linked version's own approval state**: when that version's `approval_state` is
    already `APPROVED`, the trigger lands directly on `SATISFIED` and leaves the open
    set; when it is anything else, the trigger lands on `IN_PROGRESS` and stays in the
    open set." The re-issue from `IN_PROGRESS` requires "the referenced version's
    `approval_state` [to] be `APPROVED`, rejecting with `ERR_INVALID_STATE` otherwise".

    Design: Corner/endpoints/retraining_trigger_link_version_lands_on_in_progress_then_satisfied
    """
    stack = build_stack(api, ramps=1)
    report = _warn_breach(api, stack, "2026-08-01T06:00:00Z")

    trigger = only_trigger(api, stack.model_id)
    assert trigger["status"] == "PROPOSED"
    assert trigger["model_id"] == stack.model_id
    assert trigger["drift_report_id"] == report["id"]
    assert trigger["skew_check_id"] is None
    assert trigger["retrained_version_id"] is None
    assert_urgency_snapshot(
        trigger,
        base_urgency=16.25,
        escalation_tier_bonus_pct=0,
        total_urgency=16.25,
        priority_band="LOW",
        retrain_required=False,
        stale_after="2026-10-30T06:00:00Z",
    )
    assert _open_triggers(api, stack.model_id) == 1

    acknowledged = _disposition(api, trigger["id"], "ACKNOWLEDGE")
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_by_user_id"] == USER_MLE_1
    assert (
        get_success_data(api.get_drift_report(report["id"], MLE_1))["status"]
        == "ACKNOWLEDGED"
    )

    unrelated = register_version(
        api,
        stack.model_id,
        stack.dataset_id,
        semver="1.1.0",
        artifact_digest="sha256:bbb",
    )
    assert unrelated["parent_version_id"] is None
    validate_error(
        api.disposition_retraining_trigger(
            trigger["id"],
            build_trigger_disposition_payload(
                "LINK_VERSION", retrained_version_id=unrelated["id"]
            ),
            MLE_1,
        ),
        ERR_RETRAINED_VERSION_LINEAGE_INVALID,
    )
    unmoved = get_success_data(api.get_retraining_trigger(trigger["id"], MLE_1))
    assert unmoved["status"] == "ACKNOWLEDGED"
    assert unmoved["retrained_version_id"] is None

    descendant = register_version(
        api,
        stack.model_id,
        stack.dataset_id,
        semver="1.1.1",
        artifact_digest="sha256:ccc",
        parent_version_id=stack.version_id,
    )
    assert descendant["parent_version_id"] == stack.version_id
    assert_version_state(descendant, approval_state="DRAFT")

    in_progress = _disposition(
        api, trigger["id"], "LINK_VERSION", retrained_version_id=descendant["id"]
    )
    assert in_progress["status"] == "IN_PROGRESS"
    assert in_progress["retrained_version_id"] == descendant["id"]
    assert _open_triggers(api, stack.model_id) == 1

    validate_error(
        api.disposition_retraining_trigger(
            trigger["id"],
            build_trigger_disposition_payload(
                "LINK_VERSION", retrained_version_id=unrelated["id"]
            ),
            MLE_1,
        ),
        ERR_RETRAINED_VERSION_LINEAGE_INVALID,
    )
    validate_error(
        api.disposition_retraining_trigger(
            trigger["id"],
            build_trigger_disposition_payload(
                "LINK_VERSION", retrained_version_id=descendant["id"]
            ),
            MLE_1,
        ),
        ERR_INVALID_STATE,
        409,
    )
    assert (
        get_success_data(api.get_retraining_trigger(trigger["id"], MLE_1))["status"]
        == "IN_PROGRESS"
    )

    approved = approve_version(api, descendant["id"], MLE_1, APPROVER_1)
    assert_version_state(approved, approval_state="APPROVED")

    satisfied = _disposition(
        api, trigger["id"], "LINK_VERSION", retrained_version_id=descendant["id"]
    )
    assert satisfied["status"] == "SATISFIED"
    assert satisfied["retrained_version_id"] == descendant["id"]
    assert _open_triggers(api, stack.model_id) == 0


# ─── One administrative endpoint that freezes new work only ───


def test_archiving_a_model_freezes_new_work_but_not_the_traffic_it_serves(api):
    """Two creates are refused, and the deployments already serving carry on.

    PRD 3.1: archiving is "available to `PlatformAdmin` alone, which sets
    `registry_status` to `ARCHIVED` and increments the entry's `version`", and it "is a
    soft freeze on *new* work rather than a shutdown: existing deployments keep serving
    their traffic, but registering a new artifact version against an archived entry and
    scheduling a new champion-challenger evaluation for it are both rejected with
    `ERR_MODEL_ARCHIVED`". PRD 2.6 evaluates the `expected_model_version` check
    "**before** every state rule and every business rule", so the stale token answers
    first. PRD 3.4 keeps ramping the surviving deployment, trimming its step to the
    30-point ceiling and leaving `ramp_step_index` where a partial grant found it.

    Design: Corner/endpoints/archiving_a_model_blocks_new_versions_and_evaluations_but_not_serving
    """
    arms = build_evaluation_arms(api)
    stack = arms.stack
    assert_deployment_state(
        get_success_data(api.get_deployment(arms.champion_deployment_id, ADMIN_1)),
        rollout_state="LIVE",
        traffic_pct=100.00,
    )

    before = get_success_data(api.get_model(stack.model_id, ADMIN_1))
    assert before["registry_status"] == "ACTIVE"
    assert before["champion_version_id"] == arms.champion_version_id
    stale_token = before["version"]

    archived = get_success_data(api.archive_model(stack.model_id, ADMIN_1))
    assert archived["registry_status"] == "ARCHIVED"
    assert archived["version"] == stale_token + 1
    assert archived["champion_version_id"] == arms.champion_version_id

    validate_error(
        api.create_model_version(
            build_model_version_payload(
                stack.model_id,
                stack.dataset_id,
                semver="2.0.0",
                artifact_digest="sha256:zzz",
            ),
            MLE_1,
        ),
        ERR_MODEL_ARCHIVED,
        409,
    )
    _, version_meta = validate_paginated(
        api.list_model_versions(MLE_1, {"model_id": stack.model_id})
    )
    assert version_meta["total_count"] == 2

    validate_error(
        api.schedule_challenger_evaluation(
            stack.model_id,
            build_evaluation_payload(
                arms.champion_deployment_id,
                arms.challenger_deployment_id,
                stale_token,
            ),
            RELIABILITY_1,
        ),
        ERR_STALE_MODEL_VERSION,
        412,
    )
    validate_error(
        api.schedule_challenger_evaluation(
            stack.model_id,
            build_evaluation_payload(
                arms.champion_deployment_id,
                arms.challenger_deployment_id,
                read_model_version_token(api, stack.model_id),
            ),
            RELIABILITY_1,
        ),
        ERR_MODEL_ARCHIVED,
        409,
    )
    assert (
        get_success_data(
            api.list_challenger_evaluations(
                RELIABILITY_1, {"model_id": stack.model_id}
            )
        )
        == []
    )

    still_serving = ramp(api, arms.challenger_deployment_id)
    assert_deployment_state(
        still_serving,
        rollout_state="RAMPING",
        traffic_pct=40.00,
        ramp_step_index=1,
        cumulative_ramp_delta_pct=40.00,
    )
    assert_allocated_traffic(
        get_success_data(
            api.get_serving_endpoint(arms.challenger_endpoint_id, RELIABILITY_1)
        ),
        40.00,
    )
    assert_allocated_traffic(
        get_success_data(api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)),
        100.00,
    )

    _, archived_meta = validate_paginated(
        api.list_models(ADMIN_1, {"registry_status": "ARCHIVED"})
    )
    assert archived_meta["total_count"] == 1
