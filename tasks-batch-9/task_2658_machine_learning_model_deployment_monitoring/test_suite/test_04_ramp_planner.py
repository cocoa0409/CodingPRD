"""The six-step traffic ramp planner and its headroom interaction."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    assert_allocated_traffic,
    assert_deployment_state,
    assert_ramp_step_row,
)
from test_helpers.api_errors import ERR_ENDPOINT_CAPACITY_EXHAUSTED
from test_helpers.fixtures import (
    build_stack,
    create_deployment,
    ledger_rows,
    ramp,
)
from test_helpers.test_users import RELIABILITY_1


def test_realtime_ramp_lands_on_its_first_three_checkpoints(api):
    """The realtime plan walks 5, 15 and 35 with a 30-point per-step ceiling.

    PRD 3.4: the REALTIME checkpoint table is "5.00, 15.00, 35.00, 65.00,
    100.00"; a step's raw delta is "the nominal checkpoint minus the current
    traffic", capped at 30.00 per step, and "the step index advances only when
    the new traffic equals the nominal checkpoint exactly". Each granted step
    appends one ledger row carrying the step index as it stood before the
    advance.

    Design: Difficulty/combinatorial_formula/ramp_plan_five_input_nonlinear_headroom_interaction
    """
    stack = build_stack(api, max_traffic_pct=40.00)

    first = ramp(api, stack.deployment_id)
    assert_deployment_state(
        first, rollout_state="RAMPING", traffic_pct=5.00, ramp_step_index=1
    )
    second = ramp(api, stack.deployment_id)
    assert_deployment_state(second, traffic_pct=15.00, ramp_step_index=2)
    third = ramp(api, stack.deployment_id)
    assert_deployment_state(
        third,
        traffic_pct=35.00,
        ramp_step_index=3,
        cumulative_ramp_delta_pct=35.00,
    )

    endpoint = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(endpoint, 35.00)

    rows = ledger_rows(api, stack.deployment_id)
    assert len(rows) == 3
    for index, (step_index, delta) in enumerate(
        [(0, 5.00), (1, 10.00), (2, 20.00)]
    ):
        assert_ramp_step_row(
            rows[index], step_index=step_index, delta_pct=delta, reason="RAMP_STEP"
        )


def test_realtime_reserve_exhausts_the_cluster_before_the_next_checkpoint(api):
    """A granted delta of exactly zero is a capacity refusal, not a no-op step.

    PRD 3.4: for a REALTIME deployment the planner reserves 5.00 points of the
    cluster whenever the nominal checkpoint is below the last checkpoint, and
    "if the granted delta is exactly 0.00 the ramp is refused with
    ERR_ENDPOINT_CAPACITY_EXHAUSTED". On a cluster capped at 40.00 with 35.00
    already allocated the remaining headroom is entirely inside that reserve.

    Design: Difficulty/combinatorial_formula/ramp_plan_five_input_nonlinear_headroom_interaction
    """
    stack = build_stack(api, max_traffic_pct=40.00, ramps=3)

    refused = api.ramp_deployment(stack.deployment_id, RELIABILITY_1)
    validate_error(refused, ERR_ENDPOINT_CAPACITY_EXHAUSTED)

    deployment = get_success_data(
        api.get_deployment(stack.deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(deployment, traffic_pct=35.00, ramp_step_index=3)
    assert len(ledger_rows(api, stack.deployment_id)) == 3


def test_shadow_co_tenant_reserves_nothing_and_takes_the_last_points(api):
    """The same cluster state grants a shadow arm what it refuses a realtime one.

    PRD 3.4: the 5.00-point reserve applies only to the REALTIME pattern, so a
    SHADOW deployment's headroom is the cluster's max_traffic_pct minus the
    allocated total with no reserve deducted, and "the step index advances only
    when the new traffic equals the nominal checkpoint exactly" — a clamped
    grant leaves the index where it was.

    Design: Difficulty/combinatorial_formula/ramp_plan_five_input_nonlinear_headroom_interaction
    """
    stack = build_stack(api, max_traffic_pct=40.00, ramps=3)

    shadow = create_deployment(
        api,
        stack.version_id,
        stack.endpoint_id,
        pattern="SHADOW",
        fallback_strategy="NONE",
    )
    stepped = ramp(api, shadow["id"])

    assert_deployment_state(
        stepped, rollout_state="RAMPING", traffic_pct=5.00, ramp_step_index=0
    )

    endpoint = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(endpoint, 40.00)

    exhausted = api.ramp_deployment(shadow["id"], RELIABILITY_1)
    validate_error(exhausted, ERR_ENDPOINT_CAPACITY_EXHAUSTED)
