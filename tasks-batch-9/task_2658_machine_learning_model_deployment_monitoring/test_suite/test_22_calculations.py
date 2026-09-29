"""Recomputed aggregates: what each one counts, and what it deliberately ignores."""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import (
    assert_allocated_traffic,
    assert_dataset_state,
    assert_deployment_state,
    assert_skew_outcome,
    assert_version_state,
)
from test_helpers.api_client import ApiClient
from test_helpers.factories import (
    build_deployment_payload,
    build_version_decision_payload,
)
from test_helpers.fixtures import (
    build_stack,
    create_approved_dataset,
    create_model,
    create_serving_endpoint,
    create_skew_check,
    ledger_rows,
    ramp,
    read_endpoint_version,
    register_version,
    rollout,
)
from test_helpers.test_users import APPROVER_1, MLE_1, RELIABILITY_1

# ─── The cluster traffic ledger, recomputed over one contributing set ───


def _co_tenant(
    api: ApiClient,
    version_id: str,
    endpoint_id: str,
    pattern: str,
) -> dict:
    """A second deployment on a named cluster, on that cluster's current token."""
    return get_success_data(
        api.create_deployment(
            build_deployment_payload(
                version_id,
                endpoint_id,
                read_endpoint_version(api, endpoint_id),
                pattern=pattern,
            ),
            RELIABILITY_1,
        )
    )


def _allocated(api: ApiClient, endpoint_id: str) -> dict:
    return get_success_data(api.get_serving_endpoint(endpoint_id, RELIABILITY_1))


def test_the_cluster_ledger_sums_only_its_own_serving_deployments(api):
    """Pending and retired co-tenants contribute nothing, and neither does another cluster.

    PRD 3.4: `allocated_traffic_pct` "is the sum of `traffic_pct` over exactly those
    deployments whose `serving_endpoint_id` names this cluster and whose
    `rollout_state` is `RAMPING`, `HELD`, `LIVE` or `DRAINING`, rounded half up to
    two decimals. Deployments in `PENDING`, `ROLLED_BACK` or `RETIRED` contribute
    nothing at all", and it "is never patched incrementally" but "recomputed from
    scratch after every write that could change any contributing deployment's
    `traffic_pct` or `rollout_state`". Retiring a PENDING deployment "changes the
    ledger not at all, since `PENDING` contributed 0.00 already".

    Design: Corner/calculations/endpoint_traffic_ledger_counts_only_serving_deployments_of_that_endpoint
    """
    stack = build_stack(api)
    assert_allocated_traffic(_allocated(api, stack.endpoint_id), 0.00)

    realtime = ramp(api, stack.deployment_id, 2)
    assert_deployment_state(realtime, rollout_state="RAMPING", traffic_pct=15.00)
    assert_allocated_traffic(_allocated(api, stack.endpoint_id), 15.00)

    shadow = _co_tenant(api, stack.version_id, stack.endpoint_id, "SHADOW")
    assert_deployment_state(shadow, rollout_state="PENDING", traffic_pct=0.00)
    assert_allocated_traffic(_allocated(api, stack.endpoint_id), 15.00)

    shadow_ramped = ramp(api, shadow["id"])
    assert_deployment_state(
        shadow_ramped,
        rollout_state="RAMPING",
        traffic_pct=10.00,
        ramp_step_index=1,
    )
    assert_allocated_traffic(_allocated(api, stack.endpoint_id), 25.00)

    batch = _co_tenant(api, stack.version_id, stack.endpoint_id, "BATCH")
    retired = rollout(api, batch["id"], "RETIRE")
    assert_deployment_state(retired, rollout_state="RETIRED", traffic_pct=0.00)
    assert ledger_rows(api, batch["id"]) == []
    assert_allocated_traffic(_allocated(api, stack.endpoint_id), 25.00)

    other_cluster = create_serving_endpoint(api, region="eu-west-1")
    assert_allocated_traffic(other_cluster, 0.00)
    elsewhere = _co_tenant(api, stack.version_id, other_cluster["id"], "REALTIME")
    assert_deployment_state(ramp(api, elsewhere["id"]), traffic_pct=5.00)

    assert_allocated_traffic(_allocated(api, other_cluster["id"]), 5.00)
    assert_allocated_traffic(_allocated(api, stack.endpoint_id), 25.00)

    _, meta = validate_paginated(
        api.list_deployments(
            RELIABILITY_1, {"serving_endpoint_id": stack.endpoint_id}
        )
    )
    assert meta["total_count"] == 3


# ─── The snapshot dependency counter, which drops exactly one state ───


def _read_dataset(api: ApiClient, dataset_id: str) -> dict:
    return get_success_data(api.get_training_dataset(dataset_id, MLE_1))


def test_only_rejected_versions_leave_the_snapshot_dependency_count(api):
    """A draft counts, a deprecated one still counts, a rejected one does not.

    PRD 3.2: `dependent_version_count` "is the count of artifact versions whose
    `training_dataset_id` names this snapshot and whose own `approval_state` is
    anything other than `REJECTED`. It is recomputed whenever a version is
    registered against the snapshot and whenever any version's `approval_state`
    changes. A rejected version stops being a dependency". PRD 3.3 has version
    rejection "recompute the snapshot's `dependent_version_count`" while
    deprecation merely "recomputes" it, and PRD 3.2 initialises the counter to 0.

    Design: Corner/calculations/dataset_dependency_counter_drops_only_rejected_versions
    """
    model = create_model(api)
    dataset = create_approved_dataset(api)
    assert_dataset_state(dataset, approval_state="APPROVED", dependent_version_count=0)

    first = register_version(api, model["id"], dataset["id"])
    assert_dataset_state(_read_dataset(api, dataset["id"]), dependent_version_count=1)

    second = register_version(
        api, model["id"], dataset["id"], semver="1.0.1", artifact_digest="sha256:bbb"
    )
    assert_dataset_state(_read_dataset(api, dataset["id"]), dependent_version_count=2)

    third = register_version(
        api, model["id"], dataset["id"], semver="1.0.2", artifact_digest="sha256:ccc"
    )
    assert_dataset_state(_read_dataset(api, dataset["id"]), dependent_version_count=3)

    get_success_data(api.submit_version_for_review(third["id"], MLE_1))
    rejected = get_success_data(
        api.decide_model_version(
            third["id"], build_version_decision_payload("REJECT"), APPROVER_1
        )
    )
    assert_version_state(rejected, approval_state="REJECTED")
    assert_dataset_state(_read_dataset(api, dataset["id"]), dependent_version_count=2)

    get_success_data(api.submit_version_for_review(first["id"], MLE_1))
    approved = get_success_data(
        api.decide_model_version(
            first["id"], build_version_decision_payload("APPROVE"), APPROVER_1
        )
    )
    assert_version_state(
        approved,
        approval_state="APPROVED",
        revalidation_due_at="2026-10-30T00:00:00Z",
    )
    assert_dataset_state(_read_dataset(api, dataset["id"]), dependent_version_count=2)

    deprecated = get_success_data(
        api.deprecate_model_version(first["id"], APPROVER_1)
    )
    assert_version_state(
        deprecated, approval_state="DEPRECATED", revalidation_due_at=None
    )
    assert_dataset_state(_read_dataset(api, dataset["id"]), dependent_version_count=2)

    still_draft = get_success_data(api.get_model_version(second["id"], MLE_1))
    assert_version_state(still_draft, approval_state="DRAFT")

    _, meta = validate_paginated(
        api.list_model_versions(MLE_1, {"training_dataset_id": dataset["id"]})
    )
    assert meta["total_count"] == 3


# ─── The skew ladder, over the training map's key set ───


def _open_trigger_count(api: ApiClient, model_id: str) -> int:
    return get_success_data(api.get_model(model_id, MLE_1))[
        "open_retraining_trigger_count"
    ]


def test_the_training_key_set_defines_the_features_and_missing_wins_the_ladder(api):
    """A serving-only key is invisible, and one absence outranks a blocking ratio.

    PRD 3.6: "The authoritative feature list is the key set of
    `training_feature_stats` ... and any extra key present only in
    `serving_feature_stats` is ignored entirely", `max_skew_feature` has "ties broken
    by the lexicographically smallest feature name in ASCII order — never by
    insertion order", and the ladder is "a single ordered ladder in which the first
    matching row wins: `FAIL_MISSING_FEATURE` when `missing_features` is non-empty,
    otherwise `FAIL_SKEW` when `max_skew_ratio` is at least 1.25", so "the offending
    1.2500 ratio on `amount` never gets a chance to make it `FAIL_SKEW`". Each
    failing verdict "also raises a retraining trigger, in `status` `PROPOSED`".

    Design: Corner/calculations/skew_check_uses_the_training_key_set_and_short_circuits_on_missing_feature
    """
    stack = build_stack(api, ramps=1)

    serving_only_key = create_skew_check(
        api,
        stack.version_id,
        stack.deployment_id,
        {"amount": {"mean": 1.0000}, "tenure_days": {"mean": 30.0000}},
        {
            "amount": {"mean": 1.0000},
            "tenure_days": {"mean": 30.0000},
            "promo_flag": {"mean": 0.0100},
        },
    )
    assert_skew_outcome(
        serving_only_key,
        max_skew_ratio=1.0000,
        status="PASS",
        missing_features=[],
    )
    assert serving_only_key["training_dataset_id"] == stack.dataset_id
    assert _open_trigger_count(api, stack.model_id) == 0

    tied_maximum = create_skew_check(
        api,
        stack.version_id,
        stack.deployment_id,
        {
            "amount": {"mean": 0.8000},
            "beta_feature": {"mean": 0.8000},
            "zscore": {"mean": 1.0000},
        },
        {
            "amount": {"mean": 1.0000},
            "beta_feature": {"mean": 1.0000},
            "zscore": {"mean": 1.0000},
        },
    )
    assert_skew_outcome(
        tied_maximum,
        max_skew_ratio=1.2500,
        max_skew_feature="amount",
        status="FAIL_SKEW",
        missing_features=[],
    )
    assert _open_trigger_count(api, stack.model_id) == 1

    short_circuited = create_skew_check(
        api,
        stack.version_id,
        stack.deployment_id,
        {"amount": {"mean": 0.8000}, "zscore": {"mean": 1.0000}},
        {"amount": {"mean": 1.0000}},
    )
    assert_skew_outcome(
        short_circuited,
        max_skew_ratio=1.2500,
        max_skew_feature="amount",
        status="FAIL_MISSING_FEATURE",
        missing_features=["zscore"],
    )
    assert _open_trigger_count(api, stack.model_id) == 2

    _, meta = validate_paginated(
        api.list_skew_checks(MLE_1, {"deployment_id": stack.deployment_id})
    )
    assert meta["total_count"] == 3


def test_the_ratio_is_rounded_to_four_decimals_before_the_ladder_reads_it(api):
    """Rounding half up decides the boundary, and the floor decides the divide.

    PRD 3.6 computes the symmetric ratio by "take the absolute value of the training
    `mean` and the absolute value of the serving `mean`, replace each by the larger
    of itself and 0.0001, divide the larger of the two results by the smaller, and
    round half up to four decimals", then compares that stored value against the
    ladder, whose "numeric comparisons are inclusive". PRD 2.5 carries per-feature
    skew ratios at four decimals rounded half up.

    Design: Corner/calculations/skew_ratios_are_rounded_to_four_decimals_before_the_ladder_compares_them
    """
    stack = build_stack(api, ramps=1)

    just_under = create_skew_check(
        api,
        stack.version_id,
        stack.deployment_id,
        {"amount": {"mean": 0.8000}},
        {"amount": {"mean": 0.99992}},
    )
    assert_skew_outcome(
        just_under,
        max_skew_ratio=1.2499,
        max_skew_feature="amount",
        status="WARN",
        missing_features=[],
    )
    assert _open_trigger_count(api, stack.model_id) == 0

    rounds_up_to_the_threshold = create_skew_check(
        api,
        stack.version_id,
        stack.deployment_id,
        {"amount": {"mean": 0.8000}},
        {"amount": {"mean": 0.99998}},
    )
    assert_skew_outcome(
        rounds_up_to_the_threshold,
        max_skew_ratio=1.2500,
        max_skew_feature="amount",
        status="FAIL_SKEW",
    )
    assert _open_trigger_count(api, stack.model_id) == 1

    floored_operands = create_skew_check(
        api,
        stack.version_id,
        stack.deployment_id,
        {"amount": {"mean": 0.0000}},
        {"amount": {"mean": 0.00005}},
    )
    assert_skew_outcome(
        floored_operands,
        max_skew_ratio=1.0000,
        max_skew_feature="amount",
        status="PASS",
        missing_features=[],
    )
    assert _open_trigger_count(api, stack.model_id) == 1
