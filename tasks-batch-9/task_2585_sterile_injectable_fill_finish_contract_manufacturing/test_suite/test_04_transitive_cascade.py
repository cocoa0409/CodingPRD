"""Single writes whose consequences propagate four and five levels deep.

A failed aseptic process simulation freezes a suite, suspends its batches,
quarantines them, releases their reservations and restores their lots. An action
excursion demotes a certified batch and reopens the review that certified it.
"""
from __future__ import annotations

from typing import Any, Dict

from test_helpers import constants, fixtures, get_success_data
from test_helpers.test_users import PROGRAM_MANAGER, QA_REVIEWER

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Design instance: media_fill_failure_five_level_freeze_and_component_restoration
# ---------------------------------------------------------------------------
def _suite_about_to_fail_a_simulation(api) -> Json:
    """A batch in SETUP holding an exhausted vial lot, plus a second simulation."""
    program = fixtures.build_program(
        api,
        stage=fixtures.STAGE_SCHEDULED,
        lot_quantities={"VIAL": constants.WORKED_VIAL_LINE_UNITS},
    )
    reservation = fixtures.reserve(
        api,
        program["batch_id"],
        program["lot_ids"]["VIAL"],
        constants.WORKED_VIAL_LINE_UNITS,
    )
    fixtures.setup_batch(api, program["batch_id"])

    second_fill = fixtures.create_media_fill(
        api, program["suite_id"], scheduled_run_date="2026-09-08T08:00:00Z"
    )
    fixtures.execute_media_fill(
        api,
        second_fill["id"],
        units_filled=6000,
        participating_operator_names=["OP-C"],
    )
    program.update({"reservation": reservation, "second_fill": second_fill})
    return program


def test_multi_unit_media_fill_failure_freezes_the_suite_and_suspends_its_batch(api):
    """Two turbid units invalidate the suite and quarantine the batch in setup.

    PRD 3.2: "The suite's `aseptic_qualification_status` moves to `INVALIDATED` and its `media_fill_valid_until` is set back to null; the invalidation drives `posture` to `FROZEN`; the freeze sets every batch in that suite whose `production_status` is `SCHEDULED` or `SETUP` to `SUSPENDED` and, for each such batch whose `quality_status` is neither `RELEASED` nor `REJECTED`, sets `quality_status` to `QUARANTINED`; the quarantine sets every reservation of each such batch whose `status` is `RESERVED` to `RELEASED` with `released_reason` of `SUITE_FREEZE_SUSPENSION`, increasing that reservation's lot's `quantity_available` by its `quantity_reserved`; and the restored availability returns any such lot whose `status` was `EXHAUSTED` to `RELEASED`."

    Design: Difficulty/transitive_cascade/media_fill_failure_five_level_freeze_and_component_restoration
    """
    world = _suite_about_to_fail_a_simulation(api)

    failed = fixtures.read_media_fill_out(api, world["second_fill"]["id"], 2)
    assert failed["status"] == "FAILED"
    assert failed["outcome_reason"] == "MULTI_UNIT_FAILURE"

    first_fill = fixtures.read_media_fill(api, world["media_fill_id"])
    assert first_fill["status"] == "PASSED"

    suite = fixtures.read_suite(api, world["suite_id"])
    assert suite["aseptic_qualification_status"] == "INVALIDATED"
    assert suite["media_fill_valid_until"] is None
    assert suite["posture"] == constants.POSTURE_FROZEN

    batch = fixtures.read_batch(api, world["batch_id"])
    assert batch["production_status"] == "SUSPENDED"
    assert batch["quality_status"] == "QUARANTINED"


def test_media_fill_failure_restores_the_component_ledger_and_spares_the_operators(api):
    """The exhausted lot is made whole and qualifications of other runs survive.

    PRD 3.2: "Separately, every operator qualification that cites this simulation through its `media_fill_id` and whose `status` is `QUALIFIED` is set to `REVOKED`."

    Design: Difficulty/transitive_cascade/media_fill_failure_five_level_freeze_and_component_restoration
    """
    world = _suite_about_to_fail_a_simulation(api)

    lot_before = fixtures.read_lot(api, world["lot_ids"]["VIAL"])
    assert lot_before["quantity_available"] == 0
    assert lot_before["status"] == "EXHAUSTED"

    fixtures.read_media_fill_out(api, world["second_fill"]["id"], 2)

    reservation = get_success_data(
        api.get_component_reservation(world["reservation"]["id"], PROGRAM_MANAGER), 200
    )
    assert reservation["status"] == "RELEASED"
    assert reservation["released_reason"] == "SUITE_FREEZE_SUSPENSION"

    lot_after = fixtures.read_lot(api, world["lot_ids"]["VIAL"])
    assert lot_after["quantity_available"] == constants.WORKED_VIAL_LINE_UNITS
    assert lot_after["status"] == "RELEASED"

    suite = fixtures.read_suite(api, world["suite_id"])
    assert suite["committed_minutes"] == 0

    for qualification_id in world["qualification_ids"]:
        assert (
            fixtures.read_qualification(api, qualification_id)["status"] == "QUALIFIED"
        )


# ---------------------------------------------------------------------------
# Design instance: em_action_excursion_four_level_reopens_closed_batch_record_review
# ---------------------------------------------------------------------------
def test_action_excursion_demotes_a_certified_batch_and_reopens_its_review(api):
    """One excursion walks the quality axis back and unlocks the closed review.

    PRD 3.7: "Recording one raises the suite's `open_action_excursion_count`, which per section 2.5 recomputes the suite's `posture` to `RESTRICTED`; the restriction demotes every batch of that suite whose `quality_status` is `QP_REVIEW` back to `BR_REVIEW`; and each such demotion reopens that batch's batch record review, setting its `status` from `CLOSED` to `COMPLETE_WITH_FINDINGS`, increasing its `open_findings_count` by 1 and setting `closed_at` back to null."

    Design: Difficulty/transitive_cascade/em_action_excursion_four_level_reopens_closed_batch_record_review
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_QP_REVIEW)

    sample = fixtures.record_em_sample(
        api,
        program["suite_id"],
        sample_type="VIABLE_AIR",
        cfu_count=20,
        batch_order_id=program["batch_id"],
    )
    assert sample["classification"] == "ACTION"
    assert sample["action_limit"] == 10
    assert sample["risk_index"] == 80
    assert sample["investigation_status"] == "OPEN"

    suite = fixtures.read_suite(api, program["suite_id"])
    assert suite["open_action_excursion_count"] == 1
    assert suite["posture"] == constants.POSTURE_RESTRICTED

    batch = fixtures.read_batch(api, program["batch_id"])
    assert batch["quality_status"] == "BR_REVIEW"
    assert batch["production_status"] == "FILLED"

    review = fixtures.read_review(api, program["review_id"], QA_REVIEWER)
    assert review["status"] == "COMPLETE_WITH_FINDINGS"
    assert review["open_findings_count"] == 1
    assert review["closed_at"] is None


def test_demoted_batch_keeps_its_final_releasable_figure_and_its_ledgers(api):
    """The stamped final figure survives the demotion untouched.

    PRD 3.7: "A demoted batch keeps its previously stamped `final_releasable_units` untouched; that figure is recomputed only when the review closes again."

    Design: Difficulty/transitive_cascade/em_action_excursion_four_level_reopens_closed_batch_record_review
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_QP_REVIEW)
    assert program["batch"]["final_releasable_units"] == constants.WORKED_FINAL_RELEASABLE_UNITS

    fixtures.record_em_sample(
        api,
        program["suite_id"],
        sample_type="VIABLE_AIR",
        cfu_count=20,
        batch_order_id=program["batch_id"],
    )

    batch = fixtures.read_batch(api, program["batch_id"])
    assert batch["final_releasable_units"] == constants.WORKED_FINAL_RELEASABLE_UNITS
    assert (
        batch["provisional_releasable_units"]
        == constants.WORKED_PROVISIONAL_RELEASABLE_UNITS
    )

    project = fixtures.read_project(api, program["project_id"])
    assert project["committed_demand_units"] == constants.WORKED_COMPONENT_DEMAND_UNITS
