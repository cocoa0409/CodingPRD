"""The four-hop cascade a training-data revocation opens."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    assert_allocated_traffic,
    assert_dataset_state,
    assert_deltas_sum_to,
    assert_deployment_state,
    assert_ledger_reasons,
    assert_promotion_outcome,
    assert_version_state,
)
from test_helpers.api_client import ApiClient
from test_helpers.factories import build_revocation_payload
from test_helpers.fixtures import (
    build_evaluation_arms,
    ledger_rows,
    schedule_evaluation,
)
from test_helpers.test_users import RELIABILITY_1, STEWARD_1

_REASON = "upstream PII incident in the July snapshot"


def _lineage_with_collecting_evaluation(api: ApiClient) -> tuple:
    """Two approved versions on one snapshot, both serving, one evaluation open."""
    arms = build_evaluation_arms(api)
    evaluation = schedule_evaluation(
        api,
        arms.stack.model_id,
        arms.champion_deployment_id,
        arms.challenger_deployment_id,
        RELIABILITY_1,
        reserved_samples=3000,
    )
    get_success_data(
        api.start_challenger_evaluation(evaluation["id"], RELIABILITY_1)
    )
    return arms, evaluation


def _revoke(api: ApiClient, dataset_id: str) -> dict:
    return get_success_data(
        api.revoke_training_dataset(
            dataset_id, build_revocation_payload(_REASON), STEWARD_1
        )
    )


def test_revocation_blocks_every_dependent_version(api):
    """Hop one revokes the snapshot; hop two blocks its versions.

    PRD 3.2: revoking an approved snapshot "moves it to REVOKED" and then
    "every APPROVED artifact version trained on it becomes BLOCKED with
    blocked_reason TRAINING_DATA_REVOKED". PRD 3.2 also keeps
    dependent_version_count counting every version whose approval state is
    anything other than REJECTED, so a blocked version still counts.

    Design: Difficulty/transitive_cascade/dataset_revoke_cascade_depth_four
    """
    arms, _ = _lineage_with_collecting_evaluation(api)

    revoked = _revoke(api, arms.stack.dataset_id)

    assert_dataset_state(
        revoked, approval_state="REVOKED", dependent_version_count=2
    )
    assert revoked["revocation_reason"] == _REASON

    for version_id in (arms.champion_version_id, arms.challenger_version_id):
        version = get_success_data(
            api.get_model_version(version_id, RELIABILITY_1)
        )
        assert_version_state(
            version,
            approval_state="BLOCKED",
            blocked_reason="TRAINING_DATA_REVOKED",
        )


def test_blocked_versions_drain_their_deployments_and_their_ledgers(api):
    """Hop three drains every serving deployment of a blocked version.

    PRD 3.2: the cascade takes "every deployment of those versions whose
    rollout_state is RAMPING, HELD or LIVE to DRAINING with traffic_pct 0.00,
    appending exactly one DRAIN_RELEASE ledger row carrying the negative of the
    traffic it held, and recomputing the cluster's allocated traffic."

    Design: Difficulty/transitive_cascade/dataset_revoke_cascade_depth_four
    """
    arms, _ = _lineage_with_collecting_evaluation(api)

    _revoke(api, arms.stack.dataset_id)

    champion = get_success_data(
        api.get_deployment(arms.champion_deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(
        champion,
        rollout_state="DRAINING",
        traffic_pct=0.00,
        cumulative_ramp_delta_pct=0.00,
    )
    champion_rows = ledger_rows(api, arms.champion_deployment_id)
    assert len(champion_rows) == 7
    assert_ledger_reasons(
        champion_rows, ["RAMP_STEP"] * 6 + ["DRAIN_RELEASE"]
    )
    assert champion_rows[-1]["delta_pct"] == -100.00
    assert_deltas_sum_to(champion_rows, 0.00)

    challenger = get_success_data(
        api.get_deployment(arms.challenger_deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(
        challenger,
        rollout_state="DRAINING",
        traffic_pct=0.00,
        cumulative_ramp_delta_pct=0.00,
    )
    challenger_rows = ledger_rows(api, arms.challenger_deployment_id)
    assert len(challenger_rows) == 2
    assert_ledger_reasons(challenger_rows, ["RAMP_STEP", "DRAIN_RELEASE"])
    assert challenger_rows[-1]["delta_pct"] == -10.00

    for endpoint_id in (arms.stack.endpoint_id, arms.challenger_endpoint_id):
        endpoint = get_success_data(
            api.get_serving_endpoint(endpoint_id, RELIABILITY_1)
        )
        assert_allocated_traffic(endpoint, 0.00)


def test_draining_an_arm_concludes_the_open_evaluation_inconclusive(api):
    """Hop four settles the evaluation whose arm has just left the serving set.

    PRD 3.2: the cascade takes "every challenger evaluation in COLLECTING whose
    champion or challenger arm was just drained to INCONCLUSIVE with
    criteria_failures ['DEPLOYMENT_DRAINED'] and its reserved samples returned."

    Design: Difficulty/transitive_cascade/dataset_revoke_cascade_depth_four
    """
    arms, evaluation = _lineage_with_collecting_evaluation(api)
    before = get_success_data(
        api.get_model_version(arms.challenger_version_id, RELIABILITY_1)
    )
    assert_version_state(before, evaluation_sample_budget=2000)

    _revoke(api, arms.stack.dataset_id)

    settled = get_success_data(
        api.get_challenger_evaluation(evaluation["id"], RELIABILITY_1)
    )
    assert_promotion_outcome(
        settled, status="INCONCLUSIVE", criteria_failures=["DEPLOYMENT_DRAINED"]
    )

    after = get_success_data(
        api.get_model_version(arms.challenger_version_id, RELIABILITY_1)
    )
    assert_version_state(after, evaluation_sample_budget=5000)
