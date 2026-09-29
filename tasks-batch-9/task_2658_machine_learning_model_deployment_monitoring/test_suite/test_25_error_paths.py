"""Codes reached on purpose, and the ladder that decides which one answers."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    assert_deployment_state,
    assert_drift_outcome,
    assert_health_score,
    assert_promotion_outcome,
    assert_skew_outcome,
    assert_urgency_snapshot,
    assert_version_state,
)
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_ACTIVE_EVALUATION_EXISTS,
    ERR_CHALLENGER_EVALUATION_NOT_FOUND,
    ERR_CHALLENGER_MODEL_MISMATCH,
    ERR_CHALLENGER_NOT_SERVING,
    ERR_CHALLENGER_NOT_SHADOW,
    ERR_CHAMPION_NOT_LIVE,
    ERR_CLOCK_REGRESSION,
    ERR_DEPLOYMENT_NOT_FOUND,
    ERR_DEPLOYMENT_NOT_SERVING,
    ERR_DRIFT_REPORT_NOT_FOUND,
    ERR_DUPLICATE_MODEL_NAME,
    ERR_DUPLICATE_SERVING_ENDPOINT_NAME,
    ERR_EVALUATION_NOT_MATURE,
    ERR_FEATURE_SPEC_MISMATCH,
    ERR_INVALID_BIN_PROPORTIONS,
    ERR_INVALID_FEATURE_STATS,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_METRIC_SET,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_STATE,
    ERR_LABEL_COUNT_INCONSISTENT,
    ERR_LINEAGE_MODEL_MISMATCH,
    ERR_MODEL_NOT_FOUND,
    ERR_MODEL_VERSION_NOT_FOUND,
    ERR_MONITORING_WINDOW_NOT_FOUND,
    ERR_NO_LABELED_PREDICTIONS,
    ERR_PREDICTION_INCIDENT_NOT_FOUND,
    ERR_RAMP_ALREADY_COMPLETE,
    ERR_RETRAIN_REQUIRED,
    ERR_RETRAINING_TRIGGER_NOT_FOUND,
    ERR_REVALIDATION_TASK_NOT_FOUND,
    ERR_SAMPLE_BUDGET_EXCEEDED,
    ERR_SERVING_ENDPOINT_NOT_FOUND,
    ERR_SKEW_CHECK_NOT_FOUND,
    ERR_TRAFFIC_RAMP_STEP_NOT_FOUND,
    ERR_TRAINING_DATASET_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_VERSION_NOT_APPROVED,
    ERR_WINDOW_NOT_CLOSED,
    ERR_WINDOW_NOT_ENDED,
    ERR_WINDOW_VERSION_MISMATCH,
)
from test_helpers.constants import (
    FEATURE_HASH_V1,
    FEATURE_HASH_V2,
    FLAT_BIN_PROPORTIONS,
    PROBE_UUID_D,
)
from test_helpers.factories import (
    CHAMPION_METRICS,
    build_clock_payload,
    build_conclude_payload,
    build_deployment_payload,
    build_documentation_payload,
    build_evaluation_payload,
    build_incident_payload,
    build_model_payload,
    build_model_version_payload,
    build_monitoring_window_payload,
    build_serving_endpoint_payload,
    build_skew_check_payload,
    build_trigger_disposition_payload,
    build_version_decision_payload,
)
from test_helpers.fixtures import (
    Stack,
    add_version_and_deployment,
    build_stack,
    close_window,
    create_approved_dataset,
    create_approved_version,
    create_deployment,
    create_draft_dataset,
    create_drift_report,
    create_model,
    create_serving_endpoint,
    create_skew_check,
    ramp,
    read_endpoint_version,
    read_model_version_token,
    record_window,
    register_version,
    schedule_evaluation,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN_1,
    APPROVER_1,
    EMPTY_ROLE_HEADERS,
    EMPTY_USER_ID_HEADERS,
    MLE_1,
    NO_HEADERS_AT_ALL,
    NO_ROLE_HEADERS,
    NO_USER_ID_HEADERS,
    RELIABILITY_1,
    UNDECLARED_ROLE_HEADERS,
    USER_MLE_1,
    USER_REL_1,
)

# A window body whose counts and statistics are all inside their declared
# ranges, so that only the field a test deliberately breaks can be at fault.
_SOUND_COUNTS = {
    "prediction_count": 1000,
    "labeled_prediction_count": 500,
    "correct_labeled_count": 400,
    "positive_rate": 0.30,
    "p95_latency_ms": 200,
}


# ─── The clock's own guard ───


def test_the_logical_clock_refuses_an_equal_or_earlier_instant(api):
    """Re-setting the instant the clock already holds is a rejection, not a no-op.

    PRD 2.4: "Before any operator sets it, the clock reads exactly
    `2026-08-01T00:00:00Z`". An administrative capability "replaces the clock's
    value with a supplied `current_utc` instant and reports both the new value and
    the `previous_utc` value it replaced. The clock is monotonic: a `current_utc`
    that is not strictly after the clock's present value is rejected with
    `ERR_CLOCK_REGRESSION` (HTTP 409), because rewinding it would invalidate
    instants the server has already stamped."

    Design: Corner/errors/logical_clock_rejects_an_equal_or_earlier_instant
    """
    first = set_clock(api, "2026-08-05T00:00:00Z")
    assert first["current_utc"] == "2026-08-05T00:00:00Z"
    assert first["previous_utc"] == "2026-08-01T00:00:00Z"

    validate_error(
        api.set_clock(build_clock_payload("2026-08-05T00:00:00Z"), ADMIN_1),
        ERR_CLOCK_REGRESSION,
        409,
    )
    validate_error(
        api.set_clock(build_clock_payload("2026-08-04T23:59:59Z"), ADMIN_1),
        ERR_CLOCK_REGRESSION,
        409,
    )

    forward = set_clock(api, "2026-08-05T00:00:01Z")
    assert forward["previous_utc"] == "2026-08-05T00:00:00Z", (
        "a rejected set must leave the clock exactly where it was"
    )
    assert forward["current_utc"] == "2026-08-05T00:00:01Z"


# ─── Three shape guards on one body, in their pinned order ───


def _window_attempt(api: ApiClient, stack: Stack, **overrides):
    return api.create_monitoring_window(
        build_monitoring_window_payload(
            stack.deployment_id, stack.version_id, **overrides
        ),
        RELIABILITY_1,
    )


def test_a_window_answers_bins_then_labels_then_interval(api):
    """Each pair of simultaneous violations is answered by the earlier band member.

    PRD 3.5: "`window_end` must be strictly greater than `window_start` or the
    record is rejected with `ERR_INVALID_INTERVAL`"; `labeled_prediction_count`
    "must be at least 0 and at most `prediction_count`", `correct_labeled_count`
    "must be at least 0 and at most `labeled_prediction_count`", and "violating
    either of those two orderings is rejected with
    `ERR_LABEL_COUNT_INCONSISTENT`"; `observed_bin_proportions` "must contain
    exactly five numbers, each between 0.0 and 1.0, summing to within 0.0001 of
    1.0, and otherwise is rejected with `ERR_INVALID_BIN_PROPORTIONS`". PRD 2.7
    evaluates those specialised shape codes "in this order: bin-proportion arrays
    ..., label-count consistency ..., feature-statistics maps ... and metric
    maps", and puts interval ordering in the next band down.

    Design: Corner/errors/monitoring_window_shape_guards_bins_then_labels_then_interval
    """
    stack = build_stack(api, ramps=1)

    validate_error(
        _window_attempt(
            api,
            stack,
            prediction_count=1000,
            labeled_prediction_count=2000,
            correct_labeled_count=100,
            positive_rate=0.30,
            p95_latency_ms=200,
            observed_bin_proportions=[0.25, 0.25, 0.25, 0.25],
        ),
        ERR_INVALID_BIN_PROPORTIONS,
        400,
    )
    validate_error(
        _window_attempt(
            api,
            stack,
            prediction_count=1000,
            labeled_prediction_count=2000,
            correct_labeled_count=100,
            positive_rate=0.30,
            p95_latency_ms=200,
            observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
        ),
        ERR_LABEL_COUNT_INCONSISTENT,
        400,
    )
    validate_error(
        _window_attempt(
            api,
            stack,
            prediction_count=1000,
            labeled_prediction_count=500,
            correct_labeled_count=600,
            positive_rate=0.30,
            p95_latency_ms=200,
            observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
        ),
        ERR_LABEL_COUNT_INCONSISTENT,
        400,
    )

    validate_error(
        _window_attempt(
            api,
            stack,
            window_start="2026-08-02T00:00:00Z",
            window_end="2026-08-02T00:00:00Z",
            observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
            **_SOUND_COUNTS,
        ),
        ERR_INVALID_INTERVAL,
        400,
    )
    validate_error(
        _window_attempt(
            api,
            stack,
            window_start="2026-08-02T00:00:00Z",
            window_end="2026-08-01T00:00:00Z",
            prediction_count=1000,
            labeled_prediction_count=500,
            correct_labeled_count=600,
            positive_rate=0.30,
            p95_latency_ms=200,
            observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
        ),
        ERR_LABEL_COUNT_INCONSISTENT,
        400,
    )

    validate_error(
        _window_attempt(
            api,
            stack,
            observed_bin_proportions=[0.2002, 0.20, 0.20, 0.20, 0.20],
            **_SOUND_COUNTS,
        ),
        ERR_INVALID_BIN_PROPORTIONS,
        400,
    )

    accepted = get_success_data(
        _window_attempt(
            api,
            stack,
            observed_bin_proportions=[0.2001, 0.20, 0.20, 0.20, 0.20],
            **_SOUND_COUNTS,
        )
    )
    assert accepted["status"] == "OPEN"
    assert_health_score(
        accepted, health_score=91.00, variant="PROVISIONAL", baseline_delta_pct=9.00
    )

    _, meta = validate_paginated(
        api.list_monitoring_windows(MLE_1, {"deployment_id": stack.deployment_id})
    )
    assert meta["total_count"] == 1, "a rejected body must not half-write a window"


# ─── Two state guards that lock the evidence order ───


def test_a_drift_report_needs_a_closed_window_and_closing_needs_an_elapsed_one(api):
    """The only route to a report is advance the clock, close, then score.

    PRD 3.6: "The named window's `status` must be `CLOSED`, or the create is
    rejected with `ERR_WINDOW_NOT_CLOSED`". PRD 3.5 makes closing "rejected with
    `ERR_WINDOW_NOT_ENDED` unless `window_end` is at or before the logical clock's
    present value, so a `FINAL` score is never computed over an interval that has
    not yet elapsed", and on success it "stamps `closed_at` from the logical clock,
    sets `health_score_variant` to `FINAL`, recomputes `health_score` under the
    `FINAL` variant". PRD 3.6 gives severity `NONE` when the index is below 0.10,
    and "`severity` of `NONE` produces no transition at all: the report stays in
    `status` `COMPUTED`, no trigger is raised, no health dimension moves".

    Design: Corner/errors/drift_report_requires_a_closed_window_and_closing_requires_an_elapsed_one
    """
    stack = build_stack(api, ramps=1)
    window = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
        observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
        **_SOUND_COUNTS,
    )
    assert window["status"] == "OPEN"

    validate_error(
        api.create_drift_report(
            {
                "monitoring_window_id": window["id"],
                "drift_kind": "DATA_DRIFT",
                "baseline_mode": "TRAINING_BASELINE",
            },
            MLE_1,
        ),
        ERR_WINDOW_NOT_CLOSED,
        409,
    )
    _, no_reports = validate_paginated(
        api.list_drift_reports(MLE_1, {"monitoring_window_id": window["id"]})
    )
    assert no_reports["total_count"] == 0

    validate_error(
        api.close_monitoring_window(window["id"], MLE_1), ERR_WINDOW_NOT_ENDED, 409
    )

    set_clock(api, "2026-08-03T00:00:00Z")
    closed = close_window(api, window["id"])
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] == "2026-08-03T00:00:00Z"
    assert_health_score(
        closed, health_score=86.50, variant="FINAL", baseline_delta_pct=4.50
    )

    report = create_drift_report(api, window["id"], MLE_1)
    assert_drift_outcome(
        report,
        drift_index=0.0000,
        severity="NONE",
        status="COMPUTED",
        effective_baseline_mode="TRAINING_BASELINE",
        windows_used_count=0,
        expected_bin_proportions=list(FLAT_BIN_PROPORTIONS),
    )
    assert report["baseline_dataset_id"] == stack.dataset_id
    assert report["model_version_id"] == stack.version_id

    entry = get_success_data(api.get_model(stack.model_id, MLE_1))
    assert entry["open_retraining_trigger_count"] == 0
    assert_deployment_state(
        get_success_data(api.get_deployment(stack.deployment_id, RELIABILITY_1)),
        rollout_state="RAMPING",
        health_state="HEALTHY",
    )


# ─── A range rule that refuses rather than clamps ───


def test_pagination_bounds_are_refused_rather_than_clamped(api):
    """Three near-identical requests earn three different reactions.

    PRD 2.3: "`limit` defaults to 10 when omitted, must be an integer, and must lie
    between a minimum of 1 and a maximum of 100 inclusive. `offset` defaults to 0
    when omitted, must be an integer, and must be greater than or equal to 0. An
    explicitly supplied value outside those ranges is an error, not something the
    server silently clamps: it is rejected with `ERR_INVALID_PAGINATION` (HTTP
    400)." The meta block carries "`limit`, `offset`, `total_count` and
    `has_more`", where "`total_count` is the number of rows matching the filters
    before pagination is applied, and `has_more` is true when rows remain beyond
    the current page".

    Design: Corner/errors/pagination_bounds_are_rejected_and_never_silently_clamped
    """
    entry = create_model(api)
    dataset = create_draft_dataset(api)
    register_version(api, entry["id"], dataset["id"])
    register_version(
        api,
        entry["id"],
        dataset["id"],
        semver="1.0.1",
        artifact_digest="sha256:bbb",
    )
    scope = {"model_id": entry["id"]}

    validate_error(
        api.list_model_versions(MLE_1, dict(scope, limit=0, offset=0)),
        ERR_INVALID_PAGINATION,
        400,
    )
    validate_error(
        api.list_model_versions(MLE_1, dict(scope, limit=101, offset=0)),
        ERR_INVALID_PAGINATION,
        400,
    )
    validate_error(
        api.list_model_versions(MLE_1, dict(scope, limit=10, offset=-1)),
        ERR_INVALID_PAGINATION,
        400,
    )

    rows, at_the_ceiling = validate_paginated(
        api.list_model_versions(MLE_1, dict(scope, limit=100, offset=0))
    )
    assert len(rows) == 2
    assert at_the_ceiling["limit"] == 100
    assert at_the_ceiling["total_count"] == 2
    assert at_the_ceiling["has_more"] is False

    rows, defaulted = validate_paginated(api.list_model_versions(MLE_1, dict(scope)))
    assert len(rows) == 2
    assert defaulted["limit"] == 10
    assert defaulted["offset"] == 0
    assert defaulted["total_count"] == 2
    assert defaulted["has_more"] is False

    first_page, first_meta = validate_paginated(
        api.list_model_versions(MLE_1, dict(scope, limit=1, offset=0))
    )
    assert len(first_page) == 1
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_model_versions(MLE_1, dict(scope, limit=1, offset=1))
    )
    assert len(second_page) == 1
    assert second_page[0]["id"] != first_page[0]["id"]
    assert second_meta["has_more"] is False

    beyond, beyond_meta = validate_paginated(
        api.list_model_versions(MLE_1, dict(scope, limit=1, offset=99))
    )
    assert beyond == [], "an offset past the end is an empty page, not an error"
    assert beyond_meta["total_count"] == 2
    assert beyond_meta["has_more"] is False


# ─── Five creation guards on one experiment, walked in their pinned order ───


def _schedule_attempt(api: ApiClient, model_id: str, champion: str, challenger: str, **overrides):
    return api.schedule_challenger_evaluation(
        model_id,
        build_evaluation_payload(
            champion,
            challenger,
            read_model_version_token(api, model_id),
            **overrides,
        ),
        RELIABILITY_1,
    )


def test_scheduling_an_evaluation_walks_metrics_arms_budget_then_uniqueness(api):
    """Five near-valid experiments, each stopped by exactly one gate.

    PRD 3.7: "Both `champion_metrics` and `challenger_metrics` must carry exactly the
    keys `ACCURACY_PROXY`, `CALIBRATION`, `LATENCY` and `COST` with numeric values, or
    the create is rejected with `ERR_INVALID_METRIC_SET`"; "`evaluation_ends_at` must
    be strictly greater than the logical clock's present value at creation, or the
    create is rejected with `ERR_INVALID_INTERVAL`"; both arms' versions "must each
    have a `model_id` equal to the path's `model_id`, or the create is rejected with
    `ERR_CHALLENGER_MODEL_MISMATCH`". Then "No other evaluation for the same
    `model_id` may be in `status` `SCHEDULED` or `COLLECTING`, or the create is
    rejected with `ERR_ACTIVE_EVALUATION_EXISTS`", "The challenger deployment's
    `pattern` must be `SHADOW` and the champion deployment's `pattern` must be
    `REALTIME`, or the create is rejected with `ERR_CHALLENGER_NOT_SHADOW`", and "the
    requested `reserved_samples` must not exceed the challenger version's current
    `evaluation_sample_budget`, or the create is rejected with
    `ERR_SAMPLE_BUDGET_EXCEEDED`". The version's `evaluation_sample_budget` "is its
    `evaluation_sample_quota` minus that total".

    Design: Corner/errors/challenger_evaluation_creation_guards_metrics_arms_budget_and_uniqueness
    """
    stack = build_stack(api, pattern="REALTIME")
    challenger = add_version_and_deployment(
        api, stack, pattern="SHADOW", evaluation_sample_quota=50000
    )
    foreign = build_stack(api, pattern="REALTIME")

    short_metrics = {
        key: value for key, value in CHAMPION_METRICS.items() if key != "COST"
    }
    validate_error(
        _schedule_attempt(
            api,
            stack.model_id,
            stack.deployment_id,
            challenger["deployment_id"],
            challenger_metrics=short_metrics,
        ),
        ERR_INVALID_METRIC_SET,
        400,
    )
    validate_error(
        _schedule_attempt(
            api,
            stack.model_id,
            stack.deployment_id,
            challenger["deployment_id"],
            evaluation_ends_at="2026-08-01T00:00:00Z",
        ),
        ERR_INVALID_INTERVAL,
        400,
    )
    validate_error(
        _schedule_attempt(
            api, stack.model_id, stack.deployment_id, foreign.deployment_id
        ),
        ERR_CHALLENGER_MODEL_MISMATCH,
        422,
    )
    validate_error(
        _schedule_attempt(
            api, stack.model_id, stack.deployment_id, stack.deployment_id
        ),
        ERR_CHALLENGER_NOT_SHADOW,
        422,
    )
    validate_error(
        _schedule_attempt(
            api,
            stack.model_id,
            stack.deployment_id,
            challenger["deployment_id"],
            reserved_samples=60000,
        ),
        ERR_SAMPLE_BUDGET_EXCEEDED,
        409,
    )

    before = get_success_data(api.get_model_version(challenger["version_id"], MLE_1))
    assert before["evaluation_sample_budget"] == 50000, (
        "five rejected creates must have reserved nothing"
    )
    token_before = read_model_version_token(api, stack.model_id)

    evaluation = schedule_evaluation(
        api,
        stack.model_id,
        stack.deployment_id,
        challenger["deployment_id"],
        reserved_samples=30000,
    )
    assert evaluation["status"] == "SCHEDULED"
    assert evaluation["extension_count"] == 0
    assert evaluation["promotion_score"] is None
    assert evaluation["criteria_failures"] == []
    assert evaluation["challenger_version_id"] == challenger["version_id"]
    assert evaluation["created_by_user_id"] == USER_REL_1
    assert evaluation["reserved_samples"] == 30000
    assert read_model_version_token(api, stack.model_id) == token_before + 1

    after = get_success_data(api.get_model_version(challenger["version_id"], MLE_1))
    assert after["evaluation_sample_budget"] == 20000

    validate_error(
        _schedule_attempt(
            api,
            stack.model_id,
            stack.deployment_id,
            challenger["deployment_id"],
            reserved_samples=60000,
        ),
        ERR_ACTIVE_EVALUATION_EXISTS,
        409,
    )
    _, meta = validate_paginated(
        api.list_challenger_evaluations(RELIABILITY_1, {"model_id": stack.model_id})
    )
    assert meta["total_count"] == 1


# ─── Arm-serving and maturity guards, on the same experiment ───


def test_the_arm_and_maturity_guards_of_start_and_conclude(api):
    """The challenger is asked about first, the champion second, the clock last.

    PRD 3.7: "the challenger deployment's `rollout_state` must be `RAMPING`, `HELD`
    or `LIVE`, or the request is rejected with `ERR_CHALLENGER_NOT_SERVING`, and only
    then must the champion deployment's `rollout_state` be exactly `LIVE`, or the
    request is rejected with `ERR_CHAMPION_NOT_LIVE`". Concluding "is rejected with
    `ERR_EVALUATION_NOT_MATURE` unless `evaluation_ends_at` is at or before the
    logical clock's present value ... and rejected with
    `ERR_NO_LABELED_PREDICTIONS` when `labeled_prediction_count` is 0". On the
    promoted branch "the registry entry's `champion_version_id` is set to
    `challenger_version_id` and its `champion_promoted_at` to the logical clock's
    present value", and "The reserved samples **stay consumed**". PRD 3.4 rejects a
    ramp with `ERR_RAMP_ALREADY_COMPLETE` "when the resulting index is at or beyond
    the length of the pattern's table".

    Design: Corner/errors/evaluation_start_and_conclude_arm_and_maturity_guards
    """
    stack = build_stack(api, pattern="REALTIME")
    challenger_cluster = create_serving_endpoint(
        api,
        ADMIN_1,
        serving_feature_spec_hash=stack.endpoint["serving_feature_spec_hash"],
        region="us-west-2",
    )
    challenger = add_version_and_deployment(
        api,
        stack,
        pattern="SHADOW",
        endpoint_id=challenger_cluster["id"],
        evaluation_sample_quota=50000,
    )
    evaluation = schedule_evaluation(
        api,
        stack.model_id,
        stack.deployment_id,
        challenger["deployment_id"],
        reserved_samples=30000,
    )

    assert_deployment_state(challenger["deployment"], rollout_state="PENDING")
    validate_error(
        api.start_challenger_evaluation(evaluation["id"], RELIABILITY_1),
        ERR_CHALLENGER_NOT_SERVING,
        409,
    )

    shadow_serving = ramp(api, challenger["deployment_id"])
    assert_deployment_state(
        shadow_serving, rollout_state="RAMPING", traffic_pct=10.00, ramp_step_index=1
    )
    validate_error(
        api.start_challenger_evaluation(evaluation["id"], RELIABILITY_1),
        ERR_CHAMPION_NOT_LIVE,
        409,
    )

    for expected_pct, expected_index in (
        (5.00, 1),
        (15.00, 2),
        (35.00, 3),
        (65.00, 4),
        (95.00, 4),
    ):
        assert_deployment_state(
            ramp(api, stack.deployment_id),
            rollout_state="RAMPING",
            traffic_pct=expected_pct,
            ramp_step_index=expected_index,
        )
    champion_live = ramp(api, stack.deployment_id)
    assert_deployment_state(
        champion_live, rollout_state="LIVE", traffic_pct=100.00, ramp_step_index=5
    )
    validate_error(
        api.ramp_deployment(stack.deployment_id, RELIABILITY_1),
        ERR_RAMP_ALREADY_COMPLETE,
        409,
    )
    at_champion_promotion = get_success_data(api.get_model(stack.model_id, MLE_1))
    assert at_champion_promotion["champion_version_id"] == stack.version_id

    collecting = get_success_data(
        api.start_challenger_evaluation(evaluation["id"], RELIABILITY_1)
    )
    assert collecting["status"] == "COLLECTING"

    validate_error(
        api.conclude_challenger_evaluation(
            evaluation["id"], build_conclude_payload(5000), RELIABILITY_1
        ),
        ERR_EVALUATION_NOT_MATURE,
        409,
    )

    set_clock(api, "2026-09-01T00:00:00Z")
    validate_error(
        api.conclude_challenger_evaluation(
            evaluation["id"], build_conclude_payload(0), RELIABILITY_1
        ),
        ERR_NO_LABELED_PREDICTIONS,
        422,
    )
    assert (
        get_success_data(
            api.get_challenger_evaluation(evaluation["id"], RELIABILITY_1)
        )["status"]
        == "COLLECTING"
    )

    promoted = get_success_data(
        api.conclude_challenger_evaluation(
            evaluation["id"], build_conclude_payload(5000), RELIABILITY_1
        )
    )
    assert_promotion_outcome(
        promoted, status="PROMOTED", promotion_score=0.0437, criteria_failures=[]
    )
    entry = get_success_data(api.get_model(stack.model_id, MLE_1))
    assert entry["champion_version_id"] == challenger["version_id"]
    assert entry["champion_promoted_at"] == "2026-09-01T00:00:00Z"
    assert (
        get_success_data(api.get_model_version(challenger["version_id"], MLE_1))[
            "evaluation_sample_budget"
        ]
        == 20000
    ), "PROMOTED stays inside the holding set, so the samples are never released"


# ─── A constraint gate, and the state gate that later outranks it ───


def _trigger_ids(api: ApiClient, model_id: str) -> list:
    rows, _ = validate_paginated(
        api.list_retraining_triggers(MLE_1, {"model_id": model_id, "limit": 100})
    )
    return [row["id"] for row in rows]


def _open_triggers(api: ApiClient, model_id: str) -> int:
    return get_success_data(api.get_model(model_id, MLE_1))[
        "open_retraining_trigger_count"
    ]


def test_a_high_urgency_trigger_cannot_be_dismissed(api):
    """Two triggers from the same evidence type diverge on one arithmetic threshold.

    PRD 3.6: the skew contribution "is 80 multiplied by the source check's
    `max_skew_ratio` minus 1.0, floored at 0", the tier "is chosen from
    `base_urgency` alone" where "a floor of 20 grants 10 percent, a floor of 45
    grants 25 percent", `priority_band` gives "`HIGH` at 50 or above, otherwise
    `MEDIUM` at 25 or above, otherwise `LOW`", and "`retrain_required` is true when
    `total_urgency` is at least 45". `DISMISS` "requires a `dismissed_reason` in the
    body ... and it is rejected with `ERR_RETRAIN_REQUIRED` while `retrain_required`
    is true — a trigger whose `total_urgency` reached 45 may not be waved away".
    `ACKNOWLEDGE` "moves `PROPOSED → ACKNOWLEDGED`, stamps
    `acknowledged_by_user_id` from the caller's `X-User-ID`", and PRD 2.7 evaluates
    the state band before the uniqueness and constraint band.

    Design: Corner/errors/a_high_urgency_retraining_trigger_cannot_be_dismissed
    """
    stack = build_stack(api, ramps=1)

    urgent_check = create_skew_check(
        api,
        stack.version_id,
        stack.deployment_id,
        {"amount": {"mean": 0.8000}},
        {"amount": {"mean": 1.2800}},
    )
    assert_skew_outcome(
        urgent_check, max_skew_ratio=1.6000, status="FAIL_SKEW", missing_features=[]
    )
    urgent_ids = _trigger_ids(api, stack.model_id)
    assert len(urgent_ids) == 1
    urgent_trigger_id = urgent_ids[0]

    quiet_check = create_skew_check(
        api,
        stack.version_id,
        stack.deployment_id,
        {"amount": {"mean": 0.8000}},
        {"amount": {"mean": 1.0000}},
    )
    assert_skew_outcome(
        quiet_check, max_skew_ratio=1.2500, status="FAIL_SKEW", missing_features=[]
    )
    both = _trigger_ids(api, stack.model_id)
    assert len(both) == 2
    quiet_trigger_id = next(row for row in both if row != urgent_trigger_id)
    assert _open_triggers(api, stack.model_id) == 2

    urgent = get_success_data(api.get_retraining_trigger(urgent_trigger_id, MLE_1))
    assert_urgency_snapshot(
        urgent,
        base_urgency=48.00,
        escalation_tier_bonus_pct=25,
        total_urgency=60.00,
        priority_band="HIGH",
        retrain_required=True,
        stale_after="2026-10-30T00:00:00Z",
    )
    assert urgent["skew_check_id"] == urgent_check["id"]
    assert urgent["drift_report_id"] is None

    quiet = get_success_data(api.get_retraining_trigger(quiet_trigger_id, MLE_1))
    assert_urgency_snapshot(
        quiet,
        base_urgency=20.00,
        escalation_tier_bonus_pct=10,
        total_urgency=22.00,
        priority_band="LOW",
        retrain_required=False,
    )

    validate_error(
        api.disposition_retraining_trigger(
            urgent_trigger_id,
            build_trigger_disposition_payload(
                "DISMISS", dismissed_reason="the ratio looks like a labelling bug"
            ),
            MLE_1,
        ),
        ERR_RETRAIN_REQUIRED,
        409,
    )
    assert (
        get_success_data(api.get_retraining_trigger(urgent_trigger_id, MLE_1))[
            "status"
        ]
        == "PROPOSED"
    )
    assert _open_triggers(api, stack.model_id) == 2

    dismissed = get_success_data(
        api.disposition_retraining_trigger(
            quiet_trigger_id,
            build_trigger_disposition_payload(
                "DISMISS", dismissed_reason="within seasonal tolerance"
            ),
            MLE_1,
        )
    )
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["dismissed_reason"] == "within seasonal tolerance"
    assert _open_triggers(api, stack.model_id) == 1

    acknowledged = get_success_data(
        api.disposition_retraining_trigger(
            urgent_trigger_id,
            build_trigger_disposition_payload("ACKNOWLEDGE"),
            MLE_1,
        )
    )
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_by_user_id"] == USER_MLE_1
    assert _open_triggers(api, stack.model_id) == 1

    validate_error(
        api.disposition_retraining_trigger(
            urgent_trigger_id,
            build_trigger_disposition_payload(
                "DISMISS", dismissed_reason="reconsidered after review"
            ),
            MLE_1,
        ),
        ERR_INVALID_STATE,
        409,
    )
    assert _open_triggers(api, stack.model_id) == 1


# ─── Thirteen families, thirteen distinct existence codes ───


def test_every_entity_type_answers_its_own_not_found_code(api):
    """One unknown identifier, thirteen different answers, all at 404.

    PRD 2.2 declares a per-entity existence code for every entity in the domain and
    PRD 2.7 places "path-identifier resolution, which answers the per-entity
    not-found code (HTTP 404)" immediately after authentication and role checks, so
    an unknown identifier is answered by the code of the entity the path names
    rather than by a generic one. PRD 2.10 requires that "every read of a single
    entity by identifier answers the entity's own not-found code", and PRD 3.4
    hangs both the health projection and the ramp-step history off the deployment
    path, so both answer `ERR_DEPLOYMENT_NOT_FOUND`.

    Design: Corner/errors/every_entity_type_answers_its_own_not_found_code
    """
    unknown = PROBE_UUID_D
    families = (
        (api.get_model(unknown, MLE_1), ERR_MODEL_NOT_FOUND),
        (api.get_training_dataset(unknown, MLE_1), ERR_TRAINING_DATASET_NOT_FOUND),
        (api.get_model_version(unknown, MLE_1), ERR_MODEL_VERSION_NOT_FOUND),
        (
            api.get_serving_endpoint(unknown, RELIABILITY_1),
            ERR_SERVING_ENDPOINT_NOT_FOUND,
        ),
        (api.get_deployment(unknown, RELIABILITY_1), ERR_DEPLOYMENT_NOT_FOUND),
        (
            api.get_traffic_ramp_step(unknown, RELIABILITY_1),
            ERR_TRAFFIC_RAMP_STEP_NOT_FOUND,
        ),
        (api.get_monitoring_window(unknown, MLE_1), ERR_MONITORING_WINDOW_NOT_FOUND),
        (api.get_drift_report(unknown, MLE_1), ERR_DRIFT_REPORT_NOT_FOUND),
        (api.get_skew_check(unknown, MLE_1), ERR_SKEW_CHECK_NOT_FOUND),
        (
            api.get_retraining_trigger(unknown, MLE_1),
            ERR_RETRAINING_TRIGGER_NOT_FOUND,
        ),
        (
            api.get_challenger_evaluation(unknown, RELIABILITY_1),
            ERR_CHALLENGER_EVALUATION_NOT_FOUND,
        ),
        (
            api.get_prediction_incident(unknown, RELIABILITY_1),
            ERR_PREDICTION_INCIDENT_NOT_FOUND,
        ),
        (api.get_revalidation_task(unknown, APPROVER_1), ERR_REVALIDATION_TASK_NOT_FOUND),
    )
    seen = set()
    for response, expected in families:
        validate_error(response, expected, 404)
        seen.add(expected)
    assert len(seen) == 13, "each entity family must own a distinct existence code"

    validate_error(
        api.get_deployment_health(unknown, RELIABILITY_1),
        ERR_DEPLOYMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.list_deployment_ramp_steps(unknown, RELIABILITY_1),
        ERR_DEPLOYMENT_NOT_FOUND,
        404,
    )


# ─── The identity check that runs before every other check ───


def test_requests_without_both_identity_headers_are_unauthenticated(api):
    """A missing or unrecognised role never reaches the role check, let alone the body.

    PRD 2.1: "Every request carries two headers: `X-User-ID` ... and `X-User-Role`
    ... If either header is missing or empty, or if `X-User-Role` does not name one
    of the five roles defined below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401). This check runs before everything else,
    including path-identifier resolution." PRD 2.7 confirms authentication is the
    first band and the role check only the second, so an undeclared role name
    answers 401 rather than `ERR_ROLE_NOT_PERMITTED`.

    Design: Corner/errors/requests_missing_x_user_headers_are_rejected_as_unauthenticated
    """
    body = build_model_payload()

    validate_error(api.create_model(body, NO_ROLE_HEADERS), ERR_UNAUTHENTICATED, 401)
    validate_error(
        api.create_model(body, NO_USER_ID_HEADERS), ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api.create_model(body, EMPTY_ROLE_HEADERS), ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api.create_model(body, EMPTY_USER_ID_HEADERS), ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api.create_model(body, UNDECLARED_ROLE_HEADERS),
        ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(api.list_models(NO_HEADERS_AT_ALL), ERR_UNAUTHENTICATED, 401)
    validate_error(
        api.get_model(PROBE_UUID_D, NO_HEADERS_AT_ALL), ERR_UNAUTHENTICATED, 401
    )

    accepted = get_success_data(api.create_model(body, MLE_1))
    assert accepted["name"] == body["name"], (
        "no rejected attempt may have consumed the uniqueness pair"
    )
    assert accepted["registered_by_user_id"] == USER_MLE_1
    _, meta = validate_paginated(api.list_models(MLE_1))
    assert meta["total_count"] == 1


# ─── Four identity rules, each with a legal twin ───


def test_registry_uniqueness_is_on_the_pair_and_hashes_must_match(api):
    """Every rejected identity here has a sibling that differs in one member only.

    PRD 3.1: "Registry names are unique per owning team: the pair of `name` and
    `owner_team` must not already exist ... and a collision is rejected with
    `ERR_DUPLICATE_MODEL_NAME`". PRD 3.4 makes the cluster "unique per region: the
    pair of `name` and `region` must not already exist, and a collision is rejected
    with `ERR_DUPLICATE_SERVING_ENDPOINT_NAME`", and requires that the version's
    `feature_spec_hash` "must equal the cluster's `serving_feature_spec_hash`, or the
    create is rejected with `ERR_FEATURE_SPEC_MISMATCH`". PRD 3.3 requires the
    version's `feature_spec_hash` to "equal the referenced snapshot's `feature_hash`,
    or the registration is rejected with `ERR_FEATURE_SPEC_MISMATCH`", and an
    optional `parent_version_id` whose target "must belong to the same registry
    entry, or the registration is rejected with `ERR_LINEAGE_MODEL_MISMATCH`".

    Design: Corner/errors/registry_uniqueness_pairs_and_hash_lineage_identities
    """
    risk_entry = get_success_data(
        api.create_model(
            build_model_payload(name="fraud-scorer", owner_team="risk-ml"), MLE_1
        )
    )
    validate_error(
        api.create_model(
            build_model_payload(name="fraud-scorer", owner_team="risk-ml"), MLE_1
        ),
        ERR_DUPLICATE_MODEL_NAME,
        409,
    )
    growth_entry = get_success_data(
        api.create_model(
            build_model_payload(name="fraud-scorer", owner_team="growth-ml"), MLE_1
        )
    )
    assert growth_entry["name"] == "fraud-scorer"
    assert growth_entry["id"] != risk_entry["id"]

    east = get_success_data(
        api.create_serving_endpoint(
            build_serving_endpoint_payload(
                name="rt-cluster-a",
                region="us-east-1",
                serving_feature_spec_hash=FEATURE_HASH_V1,
            ),
            ADMIN_1,
        )
    )
    validate_error(
        api.create_serving_endpoint(
            build_serving_endpoint_payload(
                name="rt-cluster-a",
                region="us-east-1",
                serving_feature_spec_hash=FEATURE_HASH_V1,
            ),
            ADMIN_1,
        ),
        ERR_DUPLICATE_SERVING_ENDPOINT_NAME,
        409,
    )
    west = get_success_data(
        api.create_serving_endpoint(
            build_serving_endpoint_payload(
                name="rt-cluster-a",
                region="us-west-2",
                serving_feature_spec_hash=FEATURE_HASH_V2,
            ),
            ADMIN_1,
        )
    )
    assert west["name"] == "rt-cluster-a"
    assert west["serving_feature_spec_hash"] == FEATURE_HASH_V2

    dataset = create_approved_dataset(api)
    assert dataset["feature_hash"] == FEATURE_HASH_V1
    validate_error(
        api.create_model_version(
            build_model_version_payload(
                risk_entry["id"], dataset["id"], feature_spec_hash="fs-v9"
            ),
            MLE_1,
        ),
        ERR_FEATURE_SPEC_MISMATCH,
        422,
    )

    foreign_parent = register_version(api, growth_entry["id"], dataset["id"])
    validate_error(
        api.create_model_version(
            build_model_version_payload(
                risk_entry["id"],
                dataset["id"],
                parent_version_id=foreign_parent["id"],
            ),
            MLE_1,
        ),
        ERR_LINEAGE_MODEL_MISMATCH,
        422,
    )

    base = create_approved_version(api, risk_entry["id"], dataset["id"])
    descendant = register_version(
        api,
        risk_entry["id"],
        dataset["id"],
        semver="1.1.0",
        artifact_digest="sha256:bbb",
        parent_version_id=base["id"],
    )
    assert descendant["parent_version_id"] == base["id"]

    validate_error(
        api.create_deployment(
            build_deployment_payload(
                base["id"], west["id"], read_endpoint_version(api, west["id"])
            ),
            RELIABILITY_1,
        ),
        ERR_FEATURE_SPEC_MISMATCH,
        422,
    )
    on_the_matching_cluster = create_deployment(api, base["id"], east["id"])
    assert_deployment_state(on_the_matching_cluster, rollout_state="PENDING")
    assert on_the_matching_cluster["serving_endpoint_id"] == east["id"]


# ─── Shape, then reference, then state, on the observation writes ───


def test_observation_writes_need_a_serving_deployment_and_the_right_version(api):
    """The same PENDING deployment earns three different codes depending on the body.

    PRD 3.5 requires the named deployment's `rollout_state` to be "`RAMPING`, `HELD`
    or `LIVE`, or the record is rejected with `ERR_DEPLOYMENT_NOT_SERVING`", and that
    "The submitted `model_version_id` must equal the deployment's own
    `model_version_id`, or the record is rejected with
    `ERR_WINDOW_VERSION_MISMATCH`". PRD 3.8 rejects an incident on a non-serving
    deployment with the same `ERR_DEPLOYMENT_NOT_SERVING`. PRD 3.6 requires that
    "`training_feature_stats` must be non-empty and every value in either map must
    carry a numeric `mean`, or the create is rejected with
    `ERR_INVALID_FEATURE_STATS`". PRD 2.7 evaluates the specialised shape codes
    before the referential cross-entity gates, and those before the temporal band
    that carries `ERR_DEPLOYMENT_NOT_SERVING`.

    Design: Corner/errors/observation_writes_require_a_serving_deployment_and_matching_version
    """
    stack = build_stack(api)
    assert_deployment_state(stack.deployment, rollout_state="PENDING")
    other_version = create_approved_version(
        api,
        stack.model_id,
        stack.dataset_id,
        MLE_1,
        APPROVER_1,
        semver="1.0.1",
        artifact_digest="sha256:bbb",
    )

    validate_error(
        _window_attempt(
            api,
            stack,
            observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
            **_SOUND_COUNTS,
        ),
        ERR_DEPLOYMENT_NOT_SERVING,
        409,
    )
    validate_error(
        api.create_prediction_incident(
            build_incident_payload(stack.deployment_id), RELIABILITY_1
        ),
        ERR_DEPLOYMENT_NOT_SERVING,
        409,
    )

    validate_error(
        api.create_skew_check(
            build_skew_check_payload(stack.version_id, stack.deployment_id, {}, {}),
            MLE_1,
        ),
        ERR_INVALID_FEATURE_STATS,
        400,
    )

    validate_error(
        api.create_monitoring_window(
            build_monitoring_window_payload(
                stack.deployment_id,
                other_version["id"],
                observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
                **_SOUND_COUNTS,
            ),
            RELIABILITY_1,
        ),
        ERR_WINDOW_VERSION_MISMATCH,
        422,
    )

    serving = ramp(api, stack.deployment_id)
    assert_deployment_state(
        serving, rollout_state="RAMPING", traffic_pct=5.00, ramp_step_index=1
    )

    validate_error(
        api.create_skew_check(
            build_skew_check_payload(
                stack.version_id,
                stack.deployment_id,
                {"amount": {"mean": 1.0000}},
                {"amount": {}},
            ),
            MLE_1,
        ),
        ERR_INVALID_FEATURE_STATS,
        400,
    )

    passing = create_skew_check(
        api,
        stack.version_id,
        stack.deployment_id,
        {"amount": {"mean": 1.0000}},
        {"amount": {"mean": 1.0000}},
    )
    assert_skew_outcome(
        passing, max_skew_ratio=1.0000, status="PASS", missing_features=[]
    )

    accepted = get_success_data(
        _window_attempt(
            api,
            stack,
            observed_bin_proportions=list(FLAT_BIN_PROPORTIONS),
            **_SOUND_COUNTS,
        )
    )
    assert accepted["status"] == "OPEN"
    assert accepted["model_version_id"] == stack.version_id
    assert_health_score(
        accepted, health_score=91.00, variant="PROVISIONAL", baseline_delta_pct=9.00
    )


# ─── One referential gate, reached from three different upstream states ───


def test_a_version_must_be_approved_before_it_can_be_deployed(api):
    """Three pre-approval states, one code, and a fourth attempt that finally lands.

    PRD 3.4: the version's `approval_state` "must be `APPROVED`, or the create is
    rejected with `ERR_VERSION_NOT_APPROVED` — an unapproved artifact never reaches
    serving infrastructure". PRD 3.3 lets the documentation PATCH be applied "from
    `DRAFT`, `PENDING_REVIEW` or `CHANGES_REQUESTED`", and "when applied from
    `CHANGES_REQUESTED` it also moves the row back to `DRAFT` and clears
    `decided_by_user_id` to null". PRD 2.6 makes the cluster's `version` "incremented
    by exactly 1 on every successful write", which a rejected write is not.

    Design: Corner/errors/a_version_that_is_not_yet_approved_cannot_be_deployed_at_any_pre_approval_state
    """
    entry = create_model(api)
    dataset = create_approved_dataset(api)
    endpoint = create_serving_endpoint(api)
    assert read_endpoint_version(api, endpoint["id"]) == 1

    version = register_version(api, entry["id"], dataset["id"])
    assert_version_state(version, approval_state="DRAFT")
    body = build_deployment_payload(version["id"], endpoint["id"], 1)

    validate_error(
        api.create_deployment(body, RELIABILITY_1), ERR_VERSION_NOT_APPROVED, 422
    )

    submitted = get_success_data(api.submit_version_for_review(version["id"], MLE_1))
    assert_version_state(submitted, approval_state="PENDING_REVIEW")
    validate_error(
        api.create_deployment(body, RELIABILITY_1), ERR_VERSION_NOT_APPROVED, 422
    )

    changes_requested = get_success_data(
        api.decide_model_version(
            version["id"],
            build_version_decision_payload(
                "REQUEST_CHANGES", note="attach the evaluation notebook"
            ),
            APPROVER_1,
        )
    )
    assert_version_state(changes_requested, approval_state="CHANGES_REQUESTED")
    validate_error(
        api.create_deployment(body, RELIABILITY_1), ERR_VERSION_NOT_APPROVED, 422
    )

    documented = get_success_data(
        api.update_version_documentation(
            version["id"], build_documentation_payload(), MLE_1
        )
    )
    assert_version_state(documented, approval_state="DRAFT")
    assert documented["decided_by_user_id"] is None
    assert documented["doc_completeness_pct"] == 80.00
    assert documented["reproducibility_score"] == 100.00
    validate_error(
        api.create_deployment(body, RELIABILITY_1), ERR_VERSION_NOT_APPROVED, 422
    )

    assert read_endpoint_version(api, endpoint["id"]) == 1, (
        "four rejected creates must not have advanced the cluster's token"
    )

    get_success_data(api.submit_version_for_review(version["id"], MLE_1))
    approved = get_success_data(
        api.decide_model_version(
            version["id"], build_version_decision_payload("APPROVE"), APPROVER_1
        )
    )
    assert_version_state(approved, approval_state="APPROVED")

    deployment = get_success_data(api.create_deployment(body, RELIABILITY_1))
    assert_deployment_state(deployment, rollout_state="PENDING", traffic_pct=0.00)
    assert deployment["created_by_user_id"] == USER_REL_1
    assert read_endpoint_version(api, endpoint["id"]) == 2
