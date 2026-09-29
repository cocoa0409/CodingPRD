"""The bounded inconclusive-then-extend cycle of a challenger evaluation."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assert_promotion_outcome, assert_version_state
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_MAX_EXTENSIONS_REACHED
from test_helpers.factories import build_conclude_payload
from test_helpers.fixtures import (
    build_evaluation_arms,
    schedule_evaluation,
    set_clock,
)
from test_helpers.test_users import RELIABILITY_1


def _collecting_evaluation(api: ApiClient) -> tuple:
    """A started evaluation reserving 1,000 of the challenger's 5,000 samples."""
    arms = build_evaluation_arms(api)
    evaluation = schedule_evaluation(
        api,
        arms.stack.model_id,
        arms.champion_deployment_id,
        arms.challenger_deployment_id,
        RELIABILITY_1,
    )
    assert evaluation["status"] == "SCHEDULED"
    assert evaluation["extension_count"] == 0
    started = get_success_data(
        api.start_challenger_evaluation(evaluation["id"], RELIABILITY_1)
    )
    assert started["status"] == "COLLECTING"
    return arms, evaluation


def _conclude(api: ApiClient, evaluation_id: str, labels: int) -> dict:
    return get_success_data(
        api.conclude_challenger_evaluation(
            evaluation_id, build_conclude_payload(labels), RELIABILITY_1
        )
    )


def _budget(api: ApiClient, version_id: str) -> int:
    return get_success_data(api.get_model_version(version_id, RELIABILITY_1))[
        "evaluation_sample_budget"
    ]


def test_insufficient_labels_alone_parks_the_evaluation_as_inconclusive(api):
    """A lone label shortfall is the inconclusive fork, not a rejection.

    PRD 3.7: "when the failure list is exactly ['INSUFFICIENT_LABELS'] the
    evaluation becomes INCONCLUSIVE and the reserved samples are returned to the
    challenger version's budget"; anything else in the list rejects. A score of
    0.0437 clears the 0.0300 minimum, so the labelled count is the only
    criterion in play.

    Design: Difficulty/non_linear_state_machine/challenger_evaluation_inconclusive_extend_cycle
    """
    arms, evaluation = _collecting_evaluation(api)
    set_clock(api, "2026-08-20T00:00:00Z")

    concluded = _conclude(api, evaluation["id"], 500)

    assert_promotion_outcome(
        concluded,
        status="INCONCLUSIVE",
        criteria_failures=["INSUFFICIENT_LABELS"],
        promotion_score=0.0437,
    )
    assert _budget(api, arms.challenger_version_id) == 5000


def test_extending_re_enters_collecting_and_moves_deadline_and_reservation(api):
    """The extension restarts collection, pushes the deadline and re-reserves.

    PRD 3.7: an extension "increments extension_count by one, clears the failure
    list, the promotion score and the metric lines, pushes evaluation_ends_at
    seven whole days later than its previous value, and adds 500 to
    reserved_samples", re-reserving from the challenger's budget.

    Design: Difficulty/non_linear_state_machine/challenger_evaluation_inconclusive_extend_cycle
    """
    arms, evaluation = _collecting_evaluation(api)
    set_clock(api, "2026-08-20T00:00:00Z")
    _conclude(api, evaluation["id"], 500)

    extended = get_success_data(
        api.extend_challenger_evaluation(evaluation["id"], RELIABILITY_1)
    )

    assert extended["status"] == "COLLECTING"
    assert extended["extension_count"] == 1
    assert extended["evaluation_ends_at"] == "2026-08-22T00:00:00Z"
    assert extended["reserved_samples"] == 1500
    assert extended["criteria_failures"] == []
    assert _budget(api, arms.challenger_version_id) == 3500


def test_the_extension_cycle_is_bounded_at_two_and_parks_inconclusive(api):
    """The same extend call succeeds twice and then refuses forever.

    PRD 3.7: an extension is permitted only "while extension_count is below 2,
    and otherwise returns ERR_MAX_EXTENSIONS_REACHED". The deadline moves seven
    whole days from its previous value rather than from the clock, and
    INCONCLUSIVE is not terminal, so the row stays parked there.

    Design: Difficulty/non_linear_state_machine/challenger_evaluation_inconclusive_extend_cycle
    """
    arms, evaluation = _collecting_evaluation(api)
    evaluation_id = evaluation["id"]
    set_clock(api, "2026-08-20T00:00:00Z")
    _conclude(api, evaluation_id, 500)
    get_success_data(api.extend_challenger_evaluation(evaluation_id, RELIABILITY_1))

    set_clock(api, "2026-08-23T00:00:00Z")
    second = _conclude(api, evaluation_id, 800)
    assert second["status"] == "INCONCLUSIVE"
    twice_extended = get_success_data(
        api.extend_challenger_evaluation(evaluation_id, RELIABILITY_1)
    )
    assert twice_extended["extension_count"] == 2
    assert twice_extended["evaluation_ends_at"] == "2026-08-29T00:00:00Z"
    assert twice_extended["reserved_samples"] == 2000

    set_clock(api, "2026-08-30T00:00:00Z")
    third = _conclude(api, evaluation_id, 900)
    assert third["status"] == "INCONCLUSIVE"

    refused = api.extend_challenger_evaluation(evaluation_id, RELIABILITY_1)
    validate_error(refused, ERR_MAX_EXTENSIONS_REACHED)

    parked = get_success_data(
        api.get_challenger_evaluation(evaluation_id, RELIABILITY_1)
    )
    assert parked["status"] == "INCONCLUSIVE"
    assert parked["extension_count"] == 2
    assert parked["evaluation_ends_at"] == "2026-08-29T00:00:00Z"

    challenger_version = get_success_data(
        api.get_model_version(arms.challenger_version_id, RELIABILITY_1)
    )
    assert_version_state(challenger_version, evaluation_sample_budget=5000)

    model = get_success_data(api.get_model(arms.stack.model_id, RELIABILITY_1))
    assert model["champion_version_id"] != arms.challenger_version_id
