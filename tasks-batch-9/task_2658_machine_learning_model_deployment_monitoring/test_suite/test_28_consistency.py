"""Immediate consistency: the write's own response is already the whole truth."""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import (
    assert_allocated_traffic,
    assert_deltas_sum_to,
    assert_deployment_state,
    assert_ledger_reasons,
    assert_ramp_step_row,
)
from test_helpers.api_client import ApiClient
from test_helpers.fixtures import build_stack, ramp, rollout
from test_helpers.test_users import RELIABILITY_1


def _cluster(api: ApiClient, endpoint_id: str) -> dict:
    return get_success_data(api.get_serving_endpoint(endpoint_id, RELIABILITY_1))


# ─── One promotion, one compensation, and no reconciliation call anywhere ───


def test_every_derived_field_and_cascade_is_visible_in_the_same_response(api):
    """Three aggregates move together; each read sees the move at the same instant.

    PRD 2.9: "The service is immediately consistent. Every cascade completes inside the
    request that triggered it; there is no deferred reconciliation, no read-repair and
    no background worker", and "Ledgers are always recomputed from their contributing
    rows, never incrementally patched ... after a rollback, a deployment's traffic is
    exactly 0.00, the sum of its ramp-step deltas is exactly 0.00, and the cluster's
    allocated traffic is exactly what it was immediately before that deployment's first
    ramp." PRD 3.4 has the ledger "recomputed from scratch after every write that could
    change any contributing deployment's `traffic_pct` or `rollout_state`", has the ramp
    that reaches `LIVE` on a `REALTIME` deployment "write the deployed
    `model_version_id` into the owning registry entry's `champion_version_id`" and stamp
    `champion_promoted_at`, and has `ROLLBACK` set "`traffic_pct` to 0.00", reset
    "`ramp_step_index` to 0", stamp `rolled_back_at`, append "exactly one ledger row
    whose `reason` is `ROLLBACK_RELEASE` and whose `delta_pct` is the negative of the
    `traffic_pct` the deployment held at the moment of rollback" so that
    `cumulative_ramp_delta_pct` "telescopes back to exactly 0.00", and rewrite the
    champion pointer "to that version's `parent_version_id` — null when the version has
    no parent".

    Design: Corner/consistency_model/every_derived_field_and_cascade_is_visible_in_the_same_response
    """
    stack = build_stack(api, pattern="REALTIME")
    assert_deployment_state(
        stack.deployment,
        rollout_state="PENDING",
        traffic_pct=0.00,
        ramp_step_index=0,
        cumulative_ramp_delta_pct=0.00,
    )
    assert stack.deployment["target_traffic_pct"] == 100.00
    assert stack.deployment["rolled_back_at"] is None

    rows, listing = validate_paginated(
        api.list_deployments(
            RELIABILITY_1,
            {"serving_endpoint_id": stack.endpoint_id, "limit": 10, "offset": 0},
        )
    )
    assert listing["total_count"] == 1, "the create is indexed before it answers"
    assert rows[0]["id"] == stack.deployment_id

    first_step = ramp(api, stack.deployment_id)
    assert_deployment_state(
        first_step,
        rollout_state="RAMPING",
        traffic_pct=5.00,
        ramp_step_index=1,
        cumulative_ramp_delta_pct=5.00,
    )
    assert_allocated_traffic(_cluster(api, stack.endpoint_id), 5.00)

    for expected_traffic, expected_index, expected_cumulative in (
        (15.00, 2, 15.00),
        (35.00, 3, 35.00),
        (65.00, 4, 65.00),
        (95.00, 4, 95.00),
    ):
        assert_deployment_state(
            ramp(api, stack.deployment_id),
            rollout_state="RAMPING",
            traffic_pct=expected_traffic,
            ramp_step_index=expected_index,
            cumulative_ramp_delta_pct=expected_cumulative,
        )

    promoted = ramp(api, stack.deployment_id)
    assert_deployment_state(
        promoted,
        rollout_state="LIVE",
        traffic_pct=100.00,
        ramp_step_index=5,
        cumulative_ramp_delta_pct=100.00,
    )

    entry = get_success_data(api.get_model(stack.model_id, RELIABILITY_1))
    assert entry["champion_version_id"] == stack.version_id
    assert entry["champion_promoted_at"] == "2026-08-01T00:00:00Z"
    assert_allocated_traffic(_cluster(api, stack.endpoint_id), 100.00)

    released = rollout(api, stack.deployment_id, "ROLLBACK")
    assert_deployment_state(
        released,
        rollout_state="ROLLED_BACK",
        traffic_pct=0.00,
        ramp_step_index=0,
        cumulative_ramp_delta_pct=0.00,
    )
    assert released["rolled_back_at"] == "2026-08-01T00:00:00Z"

    assert_allocated_traffic(_cluster(api, stack.endpoint_id), 0.00)
    after_compensation = get_success_data(api.get_model(stack.model_id, RELIABILITY_1))
    assert after_compensation["champion_version_id"] is None
    assert after_compensation["champion_promoted_at"] == "2026-08-01T00:00:00Z"

    ledger, audit = validate_paginated(
        api.list_deployment_ramp_steps(
            stack.deployment_id, RELIABILITY_1, {"limit": 10, "offset": 0}
        )
    )
    assert audit["total_count"] == 7
    assert_ledger_reasons(
        ledger,
        [
            "RAMP_STEP",
            "RAMP_STEP",
            "RAMP_STEP",
            "RAMP_STEP",
            "RAMP_STEP",
            "RAMP_STEP",
            "ROLLBACK_RELEASE",
        ],
    )
    for row, delta in zip(ledger, (5.00, 10.00, 20.00, 30.00, 30.00, 5.00)):
        assert_ramp_step_row(
            row, delta_pct=delta, reason="RAMP_STEP", health_state_at_step="HEALTHY"
        )
    assert_ramp_step_row(
        ledger[6],
        from_traffic_pct=100.00,
        to_traffic_pct=0.00,
        delta_pct=-100.00,
        reason="ROLLBACK_RELEASE",
    )
    assert_deltas_sum_to(ledger, 0.00)
