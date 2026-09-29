"""The two stale-version guards on capacity-bearing parents, and what they outrank."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    assert_allocated_traffic,
    assert_deployment_state,
    assert_version_state,
)
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_ACTIVE_EVALUATION_EXISTS,
    ERR_STALE_MODEL_VERSION,
    ERR_STALE_SERVING_ENDPOINT_VERSION,
)
from test_helpers.factories import (
    build_deployment_payload,
    build_evaluation_payload,
    build_operational_state_payload,
)
from test_helpers.fixtures import (
    add_version_and_deployment,
    build_stack,
    create_approved_dataset,
    create_approved_version,
    create_model,
    create_serving_endpoint,
    ramp,
    read_endpoint_version,
    read_model_version_token,
)
from test_helpers.test_users import ADMIN_1, MLE_1, RELIABILITY_1

_LONG_WINDOW = {"serve_until": "2026-12-31T00:00:00Z"}


def _deployment_attempt(
    api: ApiClient, version_id: str, endpoint_id: str, token: int, **overrides
):
    return api.create_deployment(
        build_deployment_payload(version_id, endpoint_id, token, **overrides),
        RELIABILITY_1,
    )


def _cluster(api: ApiClient, endpoint_id: str) -> dict:
    return get_success_data(api.get_serving_endpoint(endpoint_id, RELIABILITY_1))


# ─── Rule one: the cluster token, and the posture gate it outranks ───


def test_a_stale_cluster_token_is_refused_before_the_posture_gate(api):
    """Every write moves the parent, no rejected write does, and 412 beats the posture.

    PRD 2.6: "Creating a deployment requires a non-optional
    `expected_serving_endpoint_version` field in the request body, carrying the
    `version` the client last observed on the target serving cluster. If that value
    does not equal the cluster's current `version`, the create is rejected with
    `ERR_STALE_SERVING_ENDPOINT_VERSION` (HTTP 412) ... A successful create increments
    the cluster's `version` by 1, which is why a client that creates two deployments
    back to back must re-read the cluster between them." It also fixes the priority:
    the check "is evaluated after header authentication, role authorization,
    path-identifier resolution, body foreign-key resolution and interval shape, but
    **before** every state rule and every business rule. A stale-version request aimed
    at a frozen serving cluster therefore returns 412, not the cluster-posture error."
    PRD 3.4 adds that "Setting the posture increments the cluster's `version` by 1",
    that a new cluster "starts with `allocated_traffic_pct` of 0.00 and
    `operational_state` of `OPEN`", and that each ramp increments it once more.

    Design: Corner/cross_cutting_complexity_layers/occ_rule_one_stale_serving_endpoint_version_blocks_the_deployment_write
    """
    model = create_model(api)
    dataset = create_approved_dataset(api)
    version = create_approved_version(api, model["id"], dataset["id"])
    endpoint = create_serving_endpoint(api)
    assert endpoint["version"] == 1
    assert endpoint["operational_state"] == "OPEN"
    assert_allocated_traffic(endpoint, 0.00)

    realtime = get_success_data(
        _deployment_attempt(
            api, version["id"], endpoint["id"], 1, pattern="REALTIME", **_LONG_WINDOW
        )
    )
    assert_deployment_state(
        realtime, rollout_state="PENDING", traffic_pct=0.00, ramp_step_index=0
    )
    assert read_endpoint_version(api, endpoint["id"]) == 2

    replayed = _deployment_attempt(
        api,
        version["id"],
        endpoint["id"],
        1,
        pattern="SHADOW",
        fallback_strategy="NONE",
        **_LONG_WINDOW,
    )
    validate_error(replayed, ERR_STALE_SERVING_ENDPOINT_VERSION, 412)

    unmoved = _cluster(api, endpoint["id"])
    assert unmoved["version"] == 2, "a rejected write must not advance the parent"
    assert_allocated_traffic(unmoved, 0.00)
    _, only_one = validate_paginated(
        api.list_deployments(RELIABILITY_1, {"serving_endpoint_id": endpoint["id"]})
    )
    assert only_one["total_count"] == 1

    frozen = get_success_data(
        api.set_operational_state(
            endpoint["id"], build_operational_state_payload("FROZEN"), ADMIN_1
        )
    )
    assert frozen["operational_state"] == "FROZEN"
    assert frozen["version"] == 3

    stale_against_frozen = _deployment_attempt(
        api,
        version["id"],
        endpoint["id"],
        2,
        pattern="SHADOW",
        fallback_strategy="NONE",
        **_LONG_WINDOW,
    )
    validate_error(stale_against_frozen, ERR_STALE_SERVING_ENDPOINT_VERSION, 412)

    reopened = get_success_data(
        api.set_operational_state(
            endpoint["id"], build_operational_state_payload("OPEN"), ADMIN_1
        )
    )
    assert reopened["operational_state"] == "OPEN"
    assert reopened["version"] == 4

    shadow = get_success_data(
        _deployment_attempt(
            api,
            version["id"],
            endpoint["id"],
            4,
            pattern="SHADOW",
            fallback_strategy="NONE",
            **_LONG_WINDOW,
        )
    )
    assert shadow["pattern"] == "SHADOW"
    assert_deployment_state(shadow, rollout_state="PENDING", traffic_pct=0.00)
    assert read_endpoint_version(api, endpoint["id"]) == 5

    assert_deployment_state(
        ramp(api, realtime["id"]),
        rollout_state="RAMPING",
        traffic_pct=5.00,
        ramp_step_index=1,
    )
    settled = _cluster(api, endpoint["id"])
    assert settled["version"] == 6, "a ramp is a write on the cluster too"
    assert_allocated_traffic(settled, 5.00)


# ─── Rule two: the registry token, moved by a cascade, outranking uniqueness ───


def _schedule_attempt(
    api: ApiClient, model_id: str, champion: str, challenger: str, token: int, **overrides
):
    return api.schedule_challenger_evaluation(
        model_id,
        build_evaluation_payload(champion, challenger, token, **overrides),
        RELIABILITY_1,
    )


def test_a_stale_registry_token_is_refused_before_the_active_evaluation_rule(api):
    """A promotion the client never made invalidates its token, and 412 beats 409.

    PRD 2.6: "Scheduling a champion-challenger evaluation requires a non-optional
    `expected_model_version` field in the request body, carrying the `version` the
    client last observed on the target registry entry. If that value does not equal the
    registry entry's current `version`, the create is rejected with
    `ERR_STALE_MODEL_VERSION` (HTTP 412) ... A successful create increments the registry
    entry's `version` by 1." PRD 3.7 repeats the priority: "The check sits after
    existence and interval shape but before every state and business rule", among which
    is "No other evaluation for the same `model_id` may be in `status` `SCHEDULED` or
    `COLLECTING`, or the create is rejected with `ERR_ACTIVE_EVALUATION_EXISTS`". The
    parent moves without the client: PRD 3.3 has `APPROVE` "also increment the registry
    entry's `version` by 1", and PRD 3.4 has the ramp that reaches `LIVE` on a
    `REALTIME` deployment "write the deployed `model_version_id` into the owning
    registry entry's `champion_version_id`, stamp `champion_promoted_at` from the
    logical clock and increment the registry entry's `version` by 1".

    Design: Corner/cross_cutting_complexity_layers/occ_rule_two_stale_model_version_blocks_the_challenger_evaluation_write
    """
    stack = build_stack(api, pattern="REALTIME")
    assert stack.model["version"] == 1
    assert stack.model["champion_version_id"] is None

    second_cluster = create_serving_endpoint(api, name="rt-cluster-b")
    challenger = add_version_and_deployment(
        api,
        stack,
        endpoint_id=second_cluster["id"],
        pattern="SHADOW",
        evaluation_sample_quota=50000,
        ramps=1,
    )
    assert_deployment_state(
        challenger["deployment"], rollout_state="RAMPING", traffic_pct=10.00
    )
    token_before_promotion = read_model_version_token(api, stack.model_id)
    assert token_before_promotion == 3, "two approvals each advanced the registry entry"

    for expected_traffic, expected_index in (
        (5.00, 1),
        (15.00, 2),
        (35.00, 3),
        (65.00, 4),
        (95.00, 4),
    ):
        assert_deployment_state(
            ramp(api, stack.deployment_id),
            rollout_state="RAMPING",
            traffic_pct=expected_traffic,
            ramp_step_index=expected_index,
        )
    promoted = ramp(api, stack.deployment_id)
    assert_deployment_state(
        promoted, rollout_state="LIVE", traffic_pct=100.00, ramp_step_index=5
    )

    entry = get_success_data(api.get_model(stack.model_id, MLE_1))
    assert entry["champion_version_id"] == stack.version_id
    assert entry["champion_promoted_at"] == "2026-08-01T00:00:00Z"
    assert entry["version"] == 4, "the promotion cascade moved the parent, not the client"

    stale = _schedule_attempt(
        api,
        stack.model_id,
        stack.deployment_id,
        challenger["deployment_id"],
        token_before_promotion,
        reserved_samples=30000,
        evaluation_ends_at="2026-09-01T00:00:00Z",
    )
    validate_error(stale, ERR_STALE_MODEL_VERSION, 412)

    scheduled = get_success_data(
        _schedule_attempt(
            api,
            stack.model_id,
            stack.deployment_id,
            challenger["deployment_id"],
            4,
            reserved_samples=30000,
            evaluation_ends_at="2026-09-01T00:00:00Z",
        )
    )
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["challenger_version_id"] == challenger["version_id"]
    assert scheduled["reserved_samples"] == 30000
    assert read_model_version_token(api, stack.model_id) == 5

    stale_again = _schedule_attempt(
        api,
        stack.model_id,
        stack.deployment_id,
        challenger["deployment_id"],
        4,
        reserved_samples=5000,
        evaluation_ends_at="2026-09-01T00:00:00Z",
    )
    validate_error(stale_again, ERR_STALE_MODEL_VERSION, 412)

    refreshed_token_reaches_the_business_rule = _schedule_attempt(
        api,
        stack.model_id,
        stack.deployment_id,
        challenger["deployment_id"],
        5,
        reserved_samples=5000,
        evaluation_ends_at="2026-09-01T00:00:00Z",
    )
    validate_error(
        refreshed_token_reaches_the_business_rule, ERR_ACTIVE_EVALUATION_EXISTS, 409
    )

    assert read_model_version_token(api, stack.model_id) == 5
    assert_version_state(
        get_success_data(api.get_model_version(challenger["version_id"], MLE_1)),
        evaluation_sample_budget=20000,
    )

    read_back = get_success_data(
        api.get_challenger_evaluation(scheduled["id"], RELIABILITY_1)
    )
    assert read_back["status"] == "SCHEDULED"
    assert read_back["reserved_samples"] == 30000
    assert read_back["extension_count"] == 0
    _, meta = validate_paginated(
        api.list_challenger_evaluations(MLE_1, {"model_id": stack.model_id})
    )
    assert meta["total_count"] == 1
