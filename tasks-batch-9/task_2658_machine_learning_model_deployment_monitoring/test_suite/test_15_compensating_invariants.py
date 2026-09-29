"""Releases that hand back exactly what was taken, no more and no less."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    assert_allocated_traffic,
    assert_deltas_sum_to,
    assert_deployment_state,
    assert_ledger_reasons,
    assert_promotion_outcome,
    assert_ramp_step_row,
    assert_version_state,
)
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_SAMPLE_BUDGET_EXCEEDED
from test_helpers.factories import (
    build_conclude_payload,
    build_deployment_payload,
    build_evaluation_payload,
)
from test_helpers.fixtures import (
    build_evaluation_arms,
    build_stack,
    ledger_rows,
    ramp,
    read_endpoint_version,
    read_model_version_token,
    rollout,
    schedule_evaluation,
    set_clock,
)
from test_helpers.test_users import RELIABILITY_1

# ─── A rollback release that cancels every prior ramp step ───


def _two_co_tenants(api: ApiClient) -> tuple:
    """A realtime deployment at 35.00 and a shadow co-tenant at 10.00."""
    stack = build_stack(api)
    opened = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(opened, 0.00)

    shadow = get_success_data(
        api.create_deployment(
            build_deployment_payload(
                stack.version_id,
                stack.endpoint_id,
                read_endpoint_version(api, stack.endpoint_id),
                pattern="SHADOW",
            ),
            RELIABILITY_1,
        )
    )

    realtime = ramp(api, stack.deployment_id, 3)
    assert_deployment_state(
        realtime,
        traffic_pct=35.00,
        ramp_step_index=3,
        cumulative_ramp_delta_pct=35.00,
    )
    co_tenant = ramp(api, shadow["id"])
    assert_deployment_state(co_tenant, traffic_pct=10.00, rollout_state="RAMPING")

    peak = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(peak, 45.00)
    return stack, shadow


def test_a_rollback_writes_one_release_that_telescopes_the_ledger_to_zero(api):
    """The compensating row is the exact negative of the traffic held.

    PRD 3.4: ROLLBACK "sets traffic_pct to 0.00, resets ramp_step_index to 0,
    stamps rolled_back_at from the logical clock, and appends exactly one ledger
    row whose reason is ROLLBACK_RELEASE and whose delta_pct is the negative of the
    traffic_pct the deployment held at the moment of rollback. Because that single
    release exactly cancels every prior step, the deployment's
    cumulative_ramp_delta_pct telescopes back to exactly 0.00."

    Design: Difficulty/compensating_action_invariant/rollback_restores_endpoint_traffic_ledger_to_pre_ramp_value
    """
    stack, _ = _two_co_tenants(api)

    rolled_back = rollout(api, stack.deployment_id, "ROLLBACK")

    assert_deployment_state(
        rolled_back,
        rollout_state="ROLLED_BACK",
        traffic_pct=0.00,
        ramp_step_index=0,
        cumulative_ramp_delta_pct=0.00,
    )
    assert rolled_back["rolled_back_at"] == "2026-08-01T00:00:00Z"

    rows = ledger_rows(api, stack.deployment_id)
    assert len(rows) == 4
    assert_ledger_reasons(rows, ["RAMP_STEP"] * 3 + ["ROLLBACK_RELEASE"])
    assert_ramp_step_row(
        rows[-1],
        delta_pct=-35.00,
        to_traffic_pct=0.00,
        reason="ROLLBACK_RELEASE",
    )
    assert_deltas_sum_to(rows, 0.00)


def test_the_cluster_returns_to_its_pre_ramp_allocation_only(api):
    """The release gives back this deployment's share and nothing else.

    PRD 3.4: after a rollback "the cluster's recomputed allocated_traffic_pct
    returns to exactly the value it had immediately before this deployment's very
    first ramp", which is the co-tenant's contribution on top of the 0.00 that
    preceded it. The co-tenant is not a party to the compensating action.

    Design: Difficulty/compensating_action_invariant/rollback_restores_endpoint_traffic_ledger_to_pre_ramp_value
    """
    stack, shadow = _two_co_tenants(api)

    rollout(api, stack.deployment_id, "ROLLBACK")

    endpoint = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(endpoint, 10.00)

    co_tenant = get_success_data(api.get_deployment(shadow["id"], RELIABILITY_1))
    assert_deployment_state(
        co_tenant,
        rollout_state="RAMPING",
        traffic_pct=10.00,
        cumulative_ramp_delta_pct=10.00,
    )
    assert len(ledger_rows(api, shadow["id"])) == 1


# ─── A sample ledger that releases exactly the reservation it held ───


def _started_evaluation(api: ApiClient, reserved: int = 3000) -> tuple:
    """A COLLECTING evaluation holding a named slice of a 5,000-sample quota."""
    arms = build_evaluation_arms(api)
    evaluation = schedule_evaluation(
        api,
        arms.stack.model_id,
        arms.champion_deployment_id,
        arms.challenger_deployment_id,
        RELIABILITY_1,
        reserved_samples=reserved,
    )
    get_success_data(
        api.start_challenger_evaluation(evaluation["id"], RELIABILITY_1)
    )
    return arms, evaluation


def _budget(api: ApiClient, version_id: str) -> int:
    return get_success_data(api.get_model_version(version_id, RELIABILITY_1))[
        "evaluation_sample_budget"
    ]


def _conclude(api: ApiClient, evaluation_id: str, labels: int) -> dict:
    return get_success_data(
        api.conclude_challenger_evaluation(
            evaluation_id, build_conclude_payload(labels), RELIABILITY_1
        )
    )


def test_each_inconclusive_conclude_releases_the_current_reservation(api):
    """The release tracks the reservation as it grows, not its original size.

    PRD 3.7's sample ledger is "a recomputed ledger over the challenger version"
    whose holding set excludes INCONCLUSIVE rows, so "the release returns the
    samples the evaluation actually held, never a recomputed estimate". An
    extension adds 500 to reserved_samples and re-reserves the increased amount,
    so the second release is larger than the first.

    Design: Difficulty/compensating_action_invariant/inconclusive_conclude_releases_exactly_the_reserved_sample_budget
    """
    arms, evaluation = _started_evaluation(api)
    evaluation_id = evaluation["id"]
    assert _budget(api, arms.challenger_version_id) == 2000

    set_clock(api, "2026-08-20T00:00:00Z")
    first = _conclude(api, evaluation_id, 500)
    assert_promotion_outcome(
        first, status="INCONCLUSIVE", criteria_failures=["INSUFFICIENT_LABELS"]
    )
    assert _budget(api, arms.challenger_version_id) == 5000

    extended = get_success_data(
        api.extend_challenger_evaluation(evaluation_id, RELIABILITY_1)
    )
    assert extended["status"] == "COLLECTING"
    assert extended["extension_count"] == 1
    assert extended["evaluation_ends_at"] == "2026-08-22T00:00:00Z"
    assert extended["reserved_samples"] == 3500
    assert _budget(api, arms.challenger_version_id) == 1500

    set_clock(api, "2026-08-23T00:00:00Z")
    second = _conclude(api, evaluation_id, 500)
    assert second["status"] == "INCONCLUSIVE"
    assert _budget(api, arms.challenger_version_id) == 5000


def test_a_promotion_keeps_holding_the_samples_it_reserved(api):
    """PROMOTED stays inside the holding set, so nothing is released.

    PRD 3.7 puts SCHEDULED, COLLECTING and PROMOTED in the holding set and leaves
    only REJECTED and INCONCLUSIVE outside it, so a promotion spends the
    reservation permanently and a later evaluation asking for more than the
    remaining budget is rejected with ERR_SAMPLE_BUDGET_EXCEEDED.

    Design: Difficulty/compensating_action_invariant/inconclusive_conclude_releases_exactly_the_reserved_sample_budget
    """
    arms, evaluation = _started_evaluation(api)
    evaluation_id = evaluation["id"]
    set_clock(api, "2026-08-20T00:00:00Z")
    _conclude(api, evaluation_id, 500)
    get_success_data(api.extend_challenger_evaluation(evaluation_id, RELIABILITY_1))
    set_clock(api, "2026-08-23T00:00:00Z")
    _conclude(api, evaluation_id, 500)

    twice_extended = get_success_data(
        api.extend_challenger_evaluation(evaluation_id, RELIABILITY_1)
    )
    assert twice_extended["extension_count"] == 2
    assert twice_extended["evaluation_ends_at"] == "2026-08-29T00:00:00Z"
    assert twice_extended["reserved_samples"] == 4000
    assert _budget(api, arms.challenger_version_id) == 1000

    set_clock(api, "2026-08-30T00:00:00Z")
    promoted = _conclude(api, evaluation_id, 1000)
    assert_promotion_outcome(
        promoted,
        status="PROMOTED",
        criteria_failures=[],
        promotion_score=0.0437,
    )
    assert promoted["reserved_samples"] == 4000
    assert_version_state(
        get_success_data(
            api.get_model_version(arms.challenger_version_id, RELIABILITY_1)
        ),
        evaluation_sample_budget=1000,
    )

    refused = api.schedule_challenger_evaluation(
        arms.stack.model_id,
        build_evaluation_payload(
            arms.champion_deployment_id,
            arms.challenger_deployment_id,
            read_model_version_token(api, arms.stack.model_id),
            reserved_samples=1100,
            evaluation_ends_at="2026-09-15T00:00:00Z",
        ),
        RELIABILITY_1,
    )
    validate_error(refused, ERR_SAMPLE_BUDGET_EXCEEDED)
    assert _budget(api, arms.challenger_version_id) == 1000
    rows = get_success_data(
        api.list_challenger_evaluations(
            RELIABILITY_1, {"model_id": arms.stack.model_id}
        )
    )
    assert len(rows) == 1
