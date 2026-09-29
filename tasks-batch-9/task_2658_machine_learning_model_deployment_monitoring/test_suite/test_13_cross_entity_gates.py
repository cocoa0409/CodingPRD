"""Requests refused for the state of an entity other than their own target."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    assert_allocated_traffic,
    assert_dataset_state,
    assert_deployment_state,
    assert_version_state,
)
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_DATASET_NOT_APPROVED,
    ERR_SERVING_ENDPOINT_NOT_OPEN,
)
from test_helpers.factories import (
    build_dataset_decision_payload,
    build_deployment_payload,
    build_operational_state_payload,
    build_version_decision_payload,
)
from test_helpers.fixtures import (
    Stack,
    build_stack,
    create_approved_version,
    create_draft_dataset,
    create_model,
    ledger_rows,
    ramp,
    read_endpoint_version,
    register_version,
)
from test_helpers.test_users import (
    ADMIN_1,
    APPROVER_1,
    MLE_1,
    RELIABILITY_1,
    STEWARD_1,
)

# ─── A version decision gated by its snapshot's approval state ───


def _pending_version_on_a_draft_snapshot(api: ApiClient) -> tuple:
    """A version that is impeccable on its own terms, over a DRAFT snapshot."""
    model = create_model(api)
    dataset = create_draft_dataset(api)
    assert_dataset_state(dataset, approval_state="DRAFT")
    version = register_version(api, model["id"], dataset["id"])
    submitted = get_success_data(
        api.submit_version_for_review(version["id"], MLE_1)
    )
    assert_version_state(submitted, approval_state="PENDING_REVIEW")
    assert submitted["doc_completeness_pct"] == 80.00
    assert submitted["reproducibility_score"] == 100.00
    return dataset, version


def _approve(api: ApiClient, version_id: str):
    return api.decide_model_version(
        version_id, build_version_decision_payload("APPROVE"), APPROVER_1
    )


def _assert_version_untouched(api: ApiClient, version_id: str) -> None:
    version = get_success_data(api.get_model_version(version_id, APPROVER_1))
    assert_version_state(
        version, approval_state="PENDING_REVIEW", revalidation_due_at=None
    )
    assert version["approved_at"] is None
    assert version["decided_by_user_id"] is None


def test_a_draft_snapshot_blocks_the_approval_and_writes_nothing(api):
    """The gate reads the other entity, and the rejection writes nothing.

    PRD 3.3 requires the referenced snapshot to be APPROVED before a version may
    be approved, rejecting with ERR_DATASET_NOT_APPROVED, and PRD 2.7 places that
    among the referential cross-entity gates at 422. A request that stops on
    that gate never reaches the approval write.

    Design: Difficulty/cross_entity_state_dependency/version_approve_gated_by_training_dataset_approval_state
    """
    _, version = _pending_version_on_a_draft_snapshot(api)

    refused = _approve(api, version["id"])
    validate_error(refused, ERR_DATASET_NOT_APPROVED)

    _assert_version_untouched(api, version["id"])


def test_submitting_the_snapshot_is_not_the_same_as_approving_it(api):
    """The gate tests the dependency's current state, not merely its progress.

    PRD 3.2 makes SUBMITTED a distinct state from APPROVED on the snapshot's own
    ladder, and PRD 3.3 names APPROVED as the only state that admits the version
    decision.

    Design: Difficulty/cross_entity_state_dependency/version_approve_gated_by_training_dataset_approval_state
    """
    dataset, version = _pending_version_on_a_draft_snapshot(api)
    validate_error(_approve(api, version["id"]), ERR_DATASET_NOT_APPROVED)

    submitted = get_success_data(
        api.submit_training_dataset(dataset["id"], MLE_1)
    )
    assert_dataset_state(submitted, approval_state="SUBMITTED")

    still_refused = _approve(api, version["id"])
    validate_error(still_refused, ERR_DATASET_NOT_APPROVED)
    _assert_version_untouched(api, version["id"])


def test_approving_the_snapshot_admits_the_identical_request(api):
    """Only the dependency changed between the refusal and the acceptance.

    PRD 3.2 counts every non-REJECTED dependent version in
    dependent_version_count, and PRD 3.3 stamps approved_at from the logical clock
    and schedules the revalidation from that anchor over the registry entry's
    interval, so the downstream calculation runs on the successful call alone.

    Design: Difficulty/cross_entity_state_dependency/version_approve_gated_by_training_dataset_approval_state
    """
    dataset, version = _pending_version_on_a_draft_snapshot(api)
    validate_error(_approve(api, version["id"]), ERR_DATASET_NOT_APPROVED)
    get_success_data(api.submit_training_dataset(dataset["id"], MLE_1))
    validate_error(_approve(api, version["id"]), ERR_DATASET_NOT_APPROVED)

    approved_dataset = get_success_data(
        api.decide_training_dataset(
            dataset["id"], build_dataset_decision_payload("APPROVE"), STEWARD_1
        )
    )
    assert_dataset_state(
        approved_dataset, approval_state="APPROVED", dependent_version_count=1
    )

    accepted = get_success_data(_approve(api, version["id"]))
    assert_version_state(
        accepted,
        approval_state="APPROVED",
        revalidation_due_at="2026-10-30T00:00:00Z",
    )
    assert accepted["approved_at"] == "2026-08-01T00:00:00Z"


# ─── Deployment creation and ramping gated by the cluster's posture ───


def _set_posture(api: ApiClient, endpoint_id: str, posture: str) -> dict:
    return get_success_data(
        api.set_operational_state(
            endpoint_id, build_operational_state_payload(posture), ADMIN_1
        )
    )


def _frozen_cluster_with_one_ramped_deployment(api: ApiClient) -> Stack:
    stack = build_stack(api, ramps=1)
    opened = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert opened["operational_state"] == "OPEN"
    assert_allocated_traffic(opened, 5.00)

    frozen = _set_posture(api, stack.endpoint_id, "FROZEN")
    assert frozen["operational_state"] == "FROZEN"
    assert frozen["version"] == opened["version"] + 1
    assert_allocated_traffic(frozen, 5.00)
    return stack


def test_a_frozen_cluster_refuses_the_ramp_and_keeps_its_allocation(api):
    """The posture switch bites new traffic only, and refuses to move any.

    PRD 3.4: the posture is "a posture switch on new traffic only: existing
    allocations are untouched, but while the cluster is FROZEN or DRAINED, both
    creating a deployment on it and ramping any deployment on it are rejected with
    ERR_SERVING_ENDPOINT_NOT_OPEN". A refused ramp appends no ledger row.

    Design: Difficulty/cross_entity_state_dependency/deployment_create_and_ramp_gated_by_serving_endpoint_operational_state
    """
    stack = _frozen_cluster_with_one_ramped_deployment(api)

    refused = api.ramp_deployment(stack.deployment_id, RELIABILITY_1)
    validate_error(refused, ERR_SERVING_ENDPOINT_NOT_OPEN)

    deployment = get_success_data(
        api.get_deployment(stack.deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(
        deployment,
        rollout_state="RAMPING",
        traffic_pct=5.00,
        ramp_step_index=1,
    )
    assert len(ledger_rows(api, stack.deployment_id)) == 1
    endpoint = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(endpoint, 5.00)


def test_a_frozen_cluster_refuses_a_new_deployment_on_a_fresh_token(api):
    """The refusal is the posture gate, not a stale concurrency token.

    PRD 3.4 makes the cluster's operational_state a creation gate in its own
    right, and PRD 2.7 orders the referential cross-entity gates after the
    concurrency check, so a create carrying the cluster's current version is still
    refused for the posture alone.

    Design: Difficulty/cross_entity_state_dependency/deployment_create_and_ramp_gated_by_serving_endpoint_operational_state
    """
    stack = _frozen_cluster_with_one_ramped_deployment(api)
    second_version = create_approved_version(
        api,
        stack.model_id,
        stack.dataset_id,
        MLE_1,
        APPROVER_1,
        semver="1.1.0",
        artifact_digest="sha256:bbb",
    )
    fresh_token = read_endpoint_version(api, stack.endpoint_id)

    refused = api.create_deployment(
        build_deployment_payload(
            second_version["id"], stack.endpoint_id, fresh_token
        ),
        RELIABILITY_1,
    )
    validate_error(refused, ERR_SERVING_ENDPOINT_NOT_OPEN)

    rows = get_success_data(
        api.list_deployments(
            RELIABILITY_1, {"serving_endpoint_id": stack.endpoint_id}
        )
    )
    assert len(rows) == 1


def test_reopening_the_cluster_admits_the_identical_ramp(api):
    """Nothing about the deployment changed between the refusal and the step.

    PRD 3.4 keeps the ramp planner's checkpoints and its ledger untouched by the
    posture switch, so once the cluster is OPEN again the same call lands on the
    next nominal checkpoint and the cluster's allocation follows it.

    Design: Difficulty/cross_entity_state_dependency/deployment_create_and_ramp_gated_by_serving_endpoint_operational_state
    """
    stack = _frozen_cluster_with_one_ramped_deployment(api)
    validate_error(
        api.ramp_deployment(stack.deployment_id, RELIABILITY_1),
        ERR_SERVING_ENDPOINT_NOT_OPEN,
    )

    frozen_token = read_endpoint_version(api, stack.endpoint_id)
    reopened = _set_posture(api, stack.endpoint_id, "OPEN")
    assert reopened["operational_state"] == "OPEN"
    assert reopened["version"] == frozen_token + 1

    stepped = ramp(api, stack.deployment_id)
    assert_deployment_state(stepped, traffic_pct=15.00, ramp_step_index=2)
    endpoint = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(endpoint, 15.00)
