"""Compensating actions that must undo exactly what they undo.

Cancelling a batch has to hand back precisely the units and minutes scheduling
took, and approving a CAPA has to remove the escalated risk score the ledger is
actually carrying rather than the smaller figure first posted.
"""
from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    assertions,
    constants,
    fixtures,
    validate_paginated,
)
from test_helpers.test_users import PROGRAM_MANAGER, QA_REVIEWER, QA_REVIEWER_SECOND

Json = Dict[str, Any]


def _reservations_of_lot(api, lot_id: str):
    rows, _meta = validate_paginated(
        api.list_component_reservations(PROGRAM_MANAGER, {"component_lot_id": lot_id})
    )
    return rows


# ---------------------------------------------------------------------------
# Design instance: batch_cancellation_restores_component_unit_ledger_exactly
# ---------------------------------------------------------------------------
def _batch_in_setup_holding_two_lots(api) -> Json:
    """A batch in SETUP that has exhausted its vial lot and part of its stoppers."""
    return fixtures.build_program(
        api,
        stage=fixtures.STAGE_SETUP,
        lot_quantities={"VIAL": constants.WORKED_VIAL_LINE_UNITS},
    )


def test_cancellation_returns_every_reserved_unit_to_its_lot(api):
    """Both lots come back to their full received quantity and RELEASED status.

    PRD 3.6: "Cancellation is a compensating action and unwinds exactly what scheduling added: every `RESERVED` reservation of the batch becomes `RELEASED` with `released_reason` of `BATCH_CANCELLED` and its lot's `quantity_available` rises by its `quantity_reserved`; any lot thereby lifted above 0 returns `EXHAUSTED → RELEASED`; the project's `committed_demand_units` falls by exactly the batch's `component_demand_units`; the suite's `committed_minutes` falls by exactly the window length in minutes plus `changeover_minutes_applied`; and, unless the quality axis has already reached `RELEASED` or `REJECTED`, `quality_status` is set to `REJECTED`."

    Design: Difficulty/compensating_invariant/batch_cancellation_restores_component_unit_ledger_exactly
    """
    program = _batch_in_setup_holding_two_lots(api)

    vial_before = fixtures.read_lot(api, program["lot_ids"]["VIAL"])
    assert vial_before["quantity_available"] == 0
    assert vial_before["status"] == "EXHAUSTED"
    stopper_before = fixtures.read_lot(api, program["lot_ids"]["STOPPER"])
    assert stopper_before["quantity_available"] == 19000
    assert stopper_before["status"] == "RELEASED"

    cancelled = fixtures.cancel_batch(api, program["batch_id"], PROGRAM_MANAGER)
    assert cancelled["production_status"] == "CANCELLED"
    assert cancelled["quality_status"] == "REJECTED"

    for row in _reservations_of_lot(api, program["lot_ids"]["VIAL"]):
        assert row["status"] == "RELEASED"
        assert row["released_reason"] == "BATCH_CANCELLED"
    for row in _reservations_of_lot(api, program["lot_ids"]["STOPPER"]):
        assert row["status"] == "RELEASED"
        assert row["released_reason"] == "BATCH_CANCELLED"

    vial_after = fixtures.read_lot(api, program["lot_ids"]["VIAL"])
    assert vial_after["quantity_available"] == constants.WORKED_VIAL_LINE_UNITS
    assert vial_after["status"] == "RELEASED"
    stopper_after = fixtures.read_lot(api, program["lot_ids"]["STOPPER"])
    assert stopper_after["quantity_available"] == 30000
    assert stopper_after["status"] == "RELEASED"


def test_cancellation_returns_both_ledgers_and_keeps_the_lot_totals_balanced(api):
    """Held units plus available units still balance against what was received.

    PRD 2.6: "Several fields in this system are ledgers: they are maintained as running totals but they must always equal the aggregate they claim to represent, and every action that adds to one has an inverse that removes exactly what was added."

    Design: Difficulty/compensating_invariant/batch_cancellation_restores_component_unit_ledger_exactly
    """
    program = _batch_in_setup_holding_two_lots(api)
    fixtures.cancel_batch(api, program["batch_id"], PROGRAM_MANAGER)

    project = fixtures.read_project(api, program["project_id"])
    assert project["committed_demand_units"] == 0
    suite = fixtures.read_suite(api, program["suite_id"])
    assert suite["committed_minutes"] == 0

    for component_type, lot_id in program["lot_ids"].items():
        lot = fixtures.read_lot(api, lot_id)
        assertions.assert_lot_unit_ledger(lot, _reservations_of_lot(api, lot_id))
        assert lot["quantity_available"] == lot["quantity_received"], component_type


# ---------------------------------------------------------------------------
# Design instance:
#   capa_approval_compensates_the_escalated_risk_score_not_the_original_increment
# ---------------------------------------------------------------------------
def _project_with_two_deviations(api) -> Json:
    """A scheduled batch carrying a scored MINOR deviation and an unscored one."""
    program = fixtures.build_program(
        api, stage=fixtures.STAGE_SCHEDULED, reserved_unit_budget=50000
    )
    minor = fixtures.raise_deviation(
        api, program["batch_id"], QA_REVIEWER, summary="Documentation gap in the log."
    )
    program["minor"] = fixtures.classify_deviation(
        api, minor["id"], QA_REVIEWER, classification="MINOR"
    )
    program["escalating"] = fixtures.raise_deviation(
        api, program["batch_id"], QA_REVIEWER, summary="Line clearance queried."
    )
    return program


def test_capa_approval_removes_the_escalated_score_from_the_project_ledger(api):
    """After one rejection the ledger gives back 30, leaving only the MINOR 5.

    PRD 3.7: "An approved CAPA closes the deviation: `status` becomes `CLOSED` and the project's `open_deviation_risk_total` decreases by exactly this deviation's current `risk_score`, which returns the ledger to precisely the value it held before this deviation was classified."

    Design: Difficulty/compensating_invariant/capa_approval_compensates_the_escalated_risk_score_not_the_original_increment
    """
    program = _project_with_two_deviations(api)
    assert program["minor"]["risk_score"] == 5
    assert fixtures.read_project(api, program["project_id"])["open_deviation_risk_total"] == 5

    deviation_id = program["escalating"]["id"]
    classified = fixtures.classify_deviation(
        api, deviation_id, QA_REVIEWER, classification="MAJOR"
    )
    assert classified["risk_score"] == 20
    assert classified["status"] == "UNDER_INVESTIGATION"
    assert fixtures.read_project(api, program["project_id"])["open_deviation_risk_total"] == 25

    pending = fixtures.submit_capa(api, deviation_id, QA_REVIEWER)
    assert pending["status"] == "CAPA_PENDING"
    assert fixtures.read_project(api, program["project_id"])["open_deviation_risk_total"] == 25

    rejected = fixtures.decide_capa(
        api, deviation_id, QA_REVIEWER_SECOND, outcome="REJECTED"
    )
    assert rejected["capa_rejection_count"] == 1
    assert rejected["risk_score"] == 30
    assert rejected["status"] == "UNDER_INVESTIGATION"
    assert fixtures.read_project(api, program["project_id"])["open_deviation_risk_total"] == 35

    fixtures.submit_capa(api, deviation_id, QA_REVIEWER)
    closed = fixtures.decide_capa(
        api, deviation_id, QA_REVIEWER_SECOND, outcome="APPROVED"
    )
    assert closed["status"] == "CLOSED"
    assert closed["risk_score"] == 30

    total = fixtures.read_project(api, program["project_id"])["open_deviation_risk_total"]
    assert total == 5
    assert total != 15
    assert total != 0
    assert total != 10


def test_the_untouched_minor_deviation_and_the_batch_axes_are_left_alone(api):
    """Compensation is scoped to the one deviation that closed.

    PRD 3.7: "Classification computes `risk_score` and posts it to the owning project's `open_deviation_risk_total`, which increases by exactly the new score."

    Design: Difficulty/compensating_invariant/capa_approval_compensates_the_escalated_risk_score_not_the_original_increment
    """
    program = _project_with_two_deviations(api)
    deviation_id = program["escalating"]["id"]

    fixtures.classify_deviation(api, deviation_id, QA_REVIEWER, classification="MAJOR")
    fixtures.submit_capa(api, deviation_id, QA_REVIEWER)
    fixtures.decide_capa(api, deviation_id, QA_REVIEWER_SECOND, outcome="REJECTED")
    fixtures.submit_capa(api, deviation_id, QA_REVIEWER)
    fixtures.decide_capa(api, deviation_id, QA_REVIEWER_SECOND, outcome="APPROVED")

    minor = fixtures.read_deviation(api, program["minor"]["id"])
    assert minor["status"] == "UNDER_INVESTIGATION"
    assert minor["risk_score"] == 5
    assert minor["capa_rejection_count"] == 0

    batch = fixtures.read_batch(api, program["batch_id"])
    assert batch["quality_status"] == "PENDING"
    assert batch["production_status"] == "SCHEDULED"
