"""State machines that re-enter a state they have already left.

The CAPA loop of PRD 3.7 returns a deviation to `UNDER_INVESTIGATION` with a
strictly higher score each pass, and the quality axis of PRD 3.8 walks out of
`QUARANTINED` while the production axis never moves at all.
"""
from __future__ import annotations

from typing import Any, Dict

from test_helpers import assertions, constants, fixtures
from test_helpers.test_users import (
    QA_REVIEWER,
    QA_REVIEWER_SECOND,
    QA_REVIEWER_THIRD,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Design instance: deviation_capa_rejection_cycle_escalates_risk_on_reentry
# ---------------------------------------------------------------------------
def _linked_deviation(api) -> Json:
    """A scheduled batch carrying a deviation linked to an ACTION excursion."""
    program = fixtures.build_program(api, stage=fixtures.STAGE_SCHEDULED)
    sample = fixtures.record_em_sample(
        api, program["suite_id"], sample_type="VIABLE_AIR", cfu_count=20
    )
    deviation = fixtures.raise_deviation(
        api, program["batch_id"], QA_REVIEWER, em_sample_id=sample["id"]
    )
    program.update({"sample": sample, "deviation": deviation})
    return program


def test_capa_rejection_returns_the_deviation_to_under_investigation_with_a_higher_score(api):
    """One rejection lifts a linked MAJOR deviation from 35 points to 45.

    PRD 3.7: "As an illustration, a `MAJOR` deviation with one CAPA rejection linked to an `ACTION` sample scores 20 multiplied by 1.5, which rounds to 30, plus the 15-point linkage bonus, for 45 points."

    Design: Difficulty/non_linear_state_machine/deviation_capa_rejection_cycle_escalates_risk_on_reentry
    """
    world = _linked_deviation(api)
    deviation_id = world["deviation"]["id"]

    first_pass = fixtures.classify_deviation(
        api, deviation_id, QA_REVIEWER, classification="MAJOR"
    )
    assert first_pass["risk_score"] == 35
    assert first_pass["status"] == "UNDER_INVESTIGATION"
    assert first_pass["capa_rejection_count"] == 0

    fixtures.submit_capa(api, deviation_id, QA_REVIEWER)
    rejected = fixtures.decide_capa(
        api, deviation_id, QA_REVIEWER_SECOND, outcome="REJECTED"
    )

    assert rejected["capa_rejection_count"] == 1
    assert rejected["status"] == "UNDER_INVESTIGATION"
    assert rejected["risk_score"] == 45
    assert rejected["risk_score"] != first_pass["risk_score"]
    assertions.assert_deviation_risk(rejected, linked_to_action_sample=True)


def test_capa_rejection_adjusts_the_project_ledger_by_the_difference_only(api):
    """The project ledger holds the escalated score, not the sum of both passes.

    PRD 3.7: "A rejected CAPA loops the deviation back: `capa_rejection_count` increases by 1, `risk_score` is recomputed with the higher rejection count, the project's `open_deviation_risk_total` is adjusted by exactly the difference between the new score and the previous one, and `status` returns to `UNDER_INVESTIGATION`."

    Design: Difficulty/non_linear_state_machine/deviation_capa_rejection_cycle_escalates_risk_on_reentry
    """
    world = _linked_deviation(api)
    deviation_id = world["deviation"]["id"]

    fixtures.classify_deviation(api, deviation_id, QA_REVIEWER, classification="MAJOR")
    fixtures.submit_capa(api, deviation_id, QA_REVIEWER)
    fixtures.decide_capa(api, deviation_id, QA_REVIEWER_SECOND, outcome="REJECTED")

    project = fixtures.read_project(api, world["project_id"])
    assert project["open_deviation_risk_total"] == 45
    assert project["open_deviation_risk_total"] != 80

    batch = fixtures.read_batch(api, world["batch_id"])
    assert batch["production_status"] == "SCHEDULED"
    assert batch["quality_status"] == "PENDING"

    suite = fixtures.read_suite(api, world["suite_id"])
    assert suite["posture"] == constants.POSTURE_RESTRICTED


# ---------------------------------------------------------------------------
# Design instance:
#   batch_quality_axis_leaves_quarantine_while_production_axis_stays_filled
# ---------------------------------------------------------------------------
def _quarantined_under_review(api) -> Json:
    """A FILLED batch in BR_REVIEW carrying a fresh CRITICAL deviation."""
    program = fixtures.build_program(api, stage=fixtures.STAGE_BR_REVIEW)
    deviation = fixtures.raise_deviation(api, program["batch_id"], QA_REVIEWER_SECOND)
    program["deviation"] = fixtures.classify_deviation(
        api, deviation["id"], QA_REVIEWER_SECOND, classification="CRITICAL"
    )
    return program


def test_critical_quarantine_leaves_the_production_axis_where_it_was(api):
    """The quality axis drops to QUARANTINED while production stays FILLED.

    PRD 3.8: "The physical progress of a batch travels the production axis, and it moves independently of the quality axis on the same row: neither is a function of the other."

    Design: Difficulty/non_linear_state_machine/batch_quality_axis_leaves_quarantine_while_production_axis_stays_filled
    """
    world = _quarantined_under_review(api)

    batch = fixtures.read_batch(api, world["batch_id"])
    assert batch["quality_status"] == "QUARANTINED"
    assert batch["production_status"] == "FILLED"
    assert world["deviation"]["risk_score"] == 50

    project = fixtures.read_project(api, world["project_id"])
    assert project["status"] == "ON_HOLD"
    assert project["open_deviation_risk_total"] == 50


def test_capa_approval_walks_the_quality_axis_back_out_of_quarantine(api):
    """Closing the last open deviation returns QUARANTINED to BR_REVIEW.

    PRD 3.7: "When that approval closes the last deviation of the batch that was not already `CLOSED`, and the batch's `quality_status` is `QUARANTINED`, and its `production_status` is `FILLED`, and its suite's `posture` is not `FROZEN`, the batch's `quality_status` returns `QUARANTINED → BR_REVIEW`, closing the quarantine loop."

    Design: Difficulty/non_linear_state_machine/batch_quality_axis_leaves_quarantine_while_production_axis_stays_filled
    """
    world = _quarantined_under_review(api)
    deviation_id = world["deviation"]["id"]

    fixtures.submit_capa(api, deviation_id, QA_REVIEWER_SECOND)
    closed = fixtures.decide_capa(
        api, deviation_id, QA_REVIEWER_THIRD, outcome="APPROVED"
    )
    assert closed["status"] == "CLOSED"
    assert closed["risk_score"] == 50

    batch = fixtures.read_batch(api, world["batch_id"])
    assert batch["quality_status"] == "BR_REVIEW"
    assert batch["production_status"] == "FILLED"
    assert (
        batch["provisional_releasable_units"]
        == constants.WORKED_PROVISIONAL_RELEASABLE_UNITS
    )
    assert batch["final_releasable_units"] is None

    project = fixtures.read_project(api, world["project_id"])
    assert project["status"] == "ON_HOLD"
    assert project["open_deviation_risk_total"] == 0

    review = fixtures.read_review(api, world["review_id"])
    assert review["status"] == "IN_PROGRESS"
    assert review["open_findings_count"] == 0
