"""The pinned rounding order of the challenger promotion score."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    assert_deployment_state,
    assert_promotion_outcome,
    assert_version_state,
)
from test_helpers.api_client import ApiClient
from test_helpers.factories import build_conclude_payload
from test_helpers.fixtures import (
    EvaluationArms,
    build_evaluation_arms,
    schedule_evaluation,
    set_clock,
)
from test_helpers.test_users import RELIABILITY_1


def _started_evaluation(api: ApiClient) -> tuple:
    """A started evaluation holding 3,000 of the challenger's 5,000 samples."""
    arms: EvaluationArms = build_evaluation_arms(api)
    evaluation = schedule_evaluation(
        api,
        arms.stack.model_id,
        arms.champion_deployment_id,
        arms.challenger_deployment_id,
        RELIABILITY_1,
        reserved_samples=3000,
        evaluation_ends_at="2026-08-15T00:00:00Z",
    )
    get_success_data(
        api.start_challenger_evaluation(evaluation["id"], RELIABILITY_1)
    )
    return arms, evaluation


def test_promotion_score_rounds_each_metric_line_before_summing(api):
    """Each weighted line is rounded to four decimals before the sum.

    PRD 3.7: the promotion score "rounds twice, in a fixed order: each weighted
    metric line is rounded to four decimals first, the rounded lines are then
    summed, and the sum is rounded to four decimals again". LATENCY and COST are
    negated because lower is better, so an improvement on either produces a
    positive line.

    Design: Difficulty/combinatorial_formula/promotion_score_pinned_per_line_rounding_then_sum
    """
    _, evaluation = _started_evaluation(api)
    set_clock(api, "2026-08-20T00:00:00Z")

    concluded = get_success_data(
        api.conclude_challenger_evaluation(
            evaluation["id"], build_conclude_payload(5000), RELIABILITY_1
        )
    )

    assert_promotion_outcome(
        concluded,
        promotion_score=0.0437,
        metric_lines={
            "ACCURACY_PROXY": 0.0226,
            "CALIBRATION": 0.0029,
            "LATENCY": 0.0075,
            "COST": 0.0107,
        },
    )
    assert concluded["promotion_score"] != 0.0436
    assert concluded["metric_lines"]["LATENCY"] > 0
    assert concluded["metric_lines"]["COST"] > 0


def test_a_clean_conclusion_promotes_and_keeps_its_reservation(api):
    """An empty failure list promotes and leaves the samples consumed.

    PRD 3.7: "when the failure list is empty the evaluation becomes PROMOTED,
    the entry's champion pointer is rewritten to the challenger version,
    champion_promoted_at is stamped with the clock, and the reserved samples
    stay consumed."

    Design: Difficulty/combinatorial_formula/promotion_score_pinned_per_line_rounding_then_sum
    """
    arms, evaluation = _started_evaluation(api)
    set_clock(api, "2026-08-20T00:00:00Z")

    concluded = get_success_data(
        api.conclude_challenger_evaluation(
            evaluation["id"], build_conclude_payload(5000), RELIABILITY_1
        )
    )

    assert_promotion_outcome(concluded, status="PROMOTED", criteria_failures=[])

    model = get_success_data(api.get_model(arms.stack.model_id, RELIABILITY_1))
    assert model["champion_version_id"] == arms.challenger_version_id
    assert model["champion_promoted_at"] == "2026-08-20T00:00:00Z"

    challenger_version = get_success_data(
        api.get_model_version(arms.challenger_version_id, RELIABILITY_1)
    )
    assert_version_state(challenger_version, evaluation_sample_budget=2000)


def test_promotion_does_not_move_either_arm_s_traffic(api):
    """Concluding an evaluation is not a rollout operation.

    PRD 3.7 describes the conclusion as rewriting the champion pointer and the
    evaluation row only; PRD 3.4 makes traffic move exclusively through the ramp
    and rollout-action endpoints. Both arms therefore keep the rollout state and
    the traffic they held before the conclusion.

    Design: Difficulty/combinatorial_formula/promotion_score_pinned_per_line_rounding_then_sum
    """
    arms, evaluation = _started_evaluation(api)
    set_clock(api, "2026-08-20T00:00:00Z")
    get_success_data(
        api.conclude_challenger_evaluation(
            evaluation["id"], build_conclude_payload(5000), RELIABILITY_1
        )
    )

    champion = get_success_data(
        api.get_deployment(arms.champion_deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(champion, rollout_state="LIVE", traffic_pct=100.00)

    challenger = get_success_data(
        api.get_deployment(arms.challenger_deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(challenger, rollout_state="RAMPING", traffic_pct=10.00)
