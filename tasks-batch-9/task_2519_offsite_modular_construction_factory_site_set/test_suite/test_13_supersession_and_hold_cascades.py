"""Two cascades that travel several rows deep from a single write.

Freezing a revision that supersedes its predecessor unpins the state approval
that stamped the predecessor, which regresses the project's permit posture,
which throws every slotted module off the line and hands its minutes back to the
plant. Failing a re-inspection puts a module on hold, which unloads it, which
re-derives the load's envelope, survey and escort obligations, which empties the
lender's draft basis. Every link is asserted, not just the first.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_NO_CERTIFIABLE_WIP
from test_helpers.assertions import assert_cents, assert_module_dimensions
from test_helpers.test_users import (
    DESIGN_ENGINEER_REVIEWER,
    DESIGN_ENGINEER_SUBMITTER,
    LENDER_DRAW_ADMINISTRATOR,
    PROGRAM_ADMIN,
)


@pytest.fixture
def successor_revision_awaiting_review(api):
    """R1 frozen, stamped by state plan review and holding a slotted module.

    R2 is drawn against the same project declaring R1 as the revision it
    replaces, and is submitted and waiting for a reviewing engineer.
    """
    world = fx.world_slotted_module(api)
    successor = fx.create_design_package(
        api,
        world.project_id,
        world.project_version,
        revision_index=2,
        supersedes_package_id=world.package_id,
        connection_detail_state="COMPLETE",
    )
    validate_success(
        api.submit_design_package(
            successor["id"], f.submit_payload(review_note="R2"), DESIGN_ENGINEER_SUBMITTER
        )
    )
    return world, successor


def test_freezing_a_successor_supersedes_its_predecessor_and_unpins_the_approval(
    successor_revision_awaiting_review,
):
    """PRD §3.2: "First, the predecessor design package named by `supersedes_package_id` transitions from `FROZEN` to `SUPERSEDED` and takes a `version` increment."
    PRD §3.2: "Second, because that predecessor left `FROZEN`, every permit record whose `pinned_package_id` points at it and whose `status` is `APPROVED` transitions from `APPROVED` to `CONDITIONS_ISSUED`, has its `conditions_count` increased by 1 and its `decided_at` stamped with the current clock instant, and takes a `version` increment."

    Design: Difficulty/transitive_cascade/design_supersession_cascade_depth_five_package_permit_posture_module_ledger
    """
    world, successor = successor_revision_awaiting_review
    assert world.plan_review_permit["status"] == "APPROVED"
    assert world.plan_review_permit["pinned_package_id"] == world.package_id

    frozen = validate_success(
        world.api.decide_design_review(
            successor["id"],
            f.review_decision_payload("FREEZE"),
            DESIGN_ENGINEER_REVIEWER,
        )
    )

    assert frozen["freeze_state"] == "FROZEN"
    assert world.refresh_package()["freeze_state"] == "SUPERSEDED"

    permit = validate_success(
        world.api.get_permit(world.plan_review_permit["id"], PROGRAM_ADMIN)
    )
    assert permit["status"] == "CONDITIONS_ISSUED"
    assert permit["conditions_count"] == 1


def test_unpinning_the_state_approval_drops_the_posture_back_to_dual_blocked(
    successor_revision_awaiting_review,
):
    """PRD §3.2: "Third, because a state plan-review approval has left `APPROVED`, the project's `permit_posture` is re-derived."
    PRD §3.3: "Records in `DENIED`, `SUBMITTED`, `UNDER_REVIEW`, `CONDITIONS_ISSUED` or `EXPIRED` contribute nothing at all."
    PRD §3.3: "If none of those match, `permit_posture` is `DUAL_BLOCKED`."

    Design: Difficulty/transitive_cascade/design_supersession_cascade_depth_five_package_permit_posture_module_ledger
    """
    world, successor = successor_revision_awaiting_review
    assert world.refresh_project()["permit_posture"] == "STATE_CLEARED_ONLY"

    validate_success(
        world.api.decide_design_review(
            successor["id"],
            f.review_decision_payload("FREEZE"),
            DESIGN_ENGINEER_REVIEWER,
        )
    )

    assert world.refresh_project()["permit_posture"] == "DUAL_BLOCKED"


def test_the_reverted_module_hands_its_takt_minutes_back_to_the_plant(
    successor_revision_awaiting_review,
):
    """PRD §3.2: "Fourth, every module of the project whose `production_status` is `SLOTTED` reverts from `SLOTTED` back to `PLANNED`, clearing its `line_slot_start` and `line_slot_end` and setting its `line_slot_minutes` to 0."
    PRD §3.2: "Fifth, the minutes those reverted modules were holding are subtracted from the plant's `committed_line_minutes`, with the plant taking a `version` increment."

    Design: Difficulty/transitive_cascade/design_supersession_cascade_depth_five_package_permit_posture_module_ledger
    """
    world, successor = successor_revision_awaiting_review
    assert world.refresh_factory()["committed_line_minutes"] == 540

    validate_success(
        world.api.decide_design_review(
            successor["id"],
            f.review_decision_payload("FREEZE"),
            DESIGN_ENGINEER_REVIEWER,
        )
    )

    module = world.refresh_module()
    assert_module_dimensions(module, production_status="PLANNED")
    assert module["line_slot_start"] is None
    assert module["line_slot_end"] is None
    assert module["line_slot_minutes"] == 0
    assert world.refresh_factory()["committed_line_minutes"] == 0


@pytest.fixture
def overwide_module_aboard_a_two_state_load(api):
    """A conditionally released 200 inch module loaded for a WA to OR run.

    The load carries the overwidth consequences — survey required, escort
    required, a 100,000 cent transport permit fee — and the lender holds a draft
    deposit draw against the module's full station progress. A second final
    factory record is open and waiting for its outcome.
    """
    world = fx.world_line_complete_module(api, module_overrides={"width_in": 200})
    in_plant = fx.open_inspection(api, world.module_id(), world.agency_id, "IN_PLANT")
    fx.record_result(api, in_plant["id"], world.agency_id, "PASS")
    first_final = fx.open_inspection(
        api, world.module_id(), world.agency_id, "FINAL_FACTORY"
    )
    fx.record_result(api, first_final["id"], world.agency_id, "CONDITIONAL", 2, 2)

    world.shipment = fx.create_shipment(api, world.project_id, ["WA", "OR"])
    world.shipment = fx.load_module(
        api, world.shipment_id, world.module_id(), world.shipment["version"]
    )
    draw = fx.create_draw(api, world.project_id, world.agency_id, "WIP_DEPOSIT", 1)
    reinspection = fx.open_inspection(
        api, world.module_id(), world.agency_id, "FINAL_FACTORY"
    )
    return world, draw, reinspection


def test_a_failed_reinspection_holds_the_module_and_takes_it_off_the_load(
    overwide_module_aboard_a_two_state_load,
):
    """PRD §3.5: "A `FAIL` moves `qc_status` to `HOLD` — from `IN_PROGRESS` on a first pass, or from `CONDITIONAL_RELEASE` on a re-opened `FINAL_FACTORY` record — and requires the recording agency's `hold_authority` to be true."
    PRD §3.5: "First, if the module currently carries a `shipment_id` and that shipment's `status` is `DRAFT`, `SURVEY_REQUIRED` or `PERMITTED`, the module is unloaded: its `shipment_id` is cleared to null, its `site_status` moves from `LOADED` back to `AT_FACTORY`, the shipment's `loaded_module_count` decreases by 1, and the shipment's `status` is set back to `DRAFT`."

    Design: Difficulty/transitive_cascade/qc_hold_cascade_depth_four_module_shipment_route_permit_and_draft_draw_basis
    """
    world, _, reinspection = overwide_module_aboard_a_two_state_load
    assert world.refresh_shipment()["status"] == "SURVEY_REQUIRED"
    assert world.shipment["loaded_module_count"] == 1

    recorded = validate_success(
        world.api.record_inspection_result(
            reinspection["id"],
            f.inspection_result_payload("FAIL", 3, 4),
            world.inspector,
        )
    )

    assert recorded["hold_state"] == "AGENCY_HOLD"
    module = world.refresh_module()
    assert_module_dimensions(module, qc_status="HOLD", site_status="AT_FACTORY")
    assert module["shipment_id"] is None
    shipment = world.refresh_shipment()
    assert shipment["status"] == "DRAFT"
    assert shipment["loaded_module_count"] == 0


def test_the_emptied_load_gives_back_its_survey_escort_and_permit_obligations(
    overwide_module_aboard_a_two_state_load,
):
    """PRD §3.5: "Second, because the load changed, the shipment's `max_envelope_class` is recomputed over the modules still aboard and its `route_survey_state`, `escort_required`, `permit_expires_at` and `permit_fee_cents` are all reset accordingly by the rules in §3.6."
    PRD §3.6: "When the last non-standard module leaves the load — whether through the quality-hold cascade of §3.5 or through cancellation — and the recomputed `max_envelope_class` falls back to `STANDARD`, the survey axis moves from `REQUIRED` back to `NOT_REQUIRED`, `escort_required` is set false, and `permit_fee_cents` is set to 0 while `permit_expires_at` and `survey_completed_at` are both cleared to null."

    Design: Difficulty/transitive_cascade/qc_hold_cascade_depth_four_module_shipment_route_permit_and_draft_draw_basis
    """
    world, _, reinspection = overwide_module_aboard_a_two_state_load
    before = world.refresh_shipment()
    assert before["max_envelope_class"] == "OVERWIDTH"
    assert before["route_survey_state"] == "REQUIRED"
    assert before["escort_required"] is True
    assert_cents(before["permit_fee_cents"], 100000, "permit_fee_cents")

    validate_success(
        world.api.record_inspection_result(
            reinspection["id"],
            f.inspection_result_payload("FAIL", 3, 4),
            world.inspector,
        )
    )

    after = world.refresh_shipment()
    assert after["max_envelope_class"] == "STANDARD"
    assert after["route_survey_state"] == "NOT_REQUIRED"
    assert after["escort_required"] is False
    assert after["escort_confirmed"] is False
    assert after["permit_expires_at"] is None
    assert_cents(after["permit_fee_cents"], 0, "permit_fee_cents")


def test_the_held_module_leaves_the_draft_draw_basis_entirely(
    overwide_module_aboard_a_two_state_load,
):
    """PRD §3.5: "Third, the `basis_earned_cents` and `requested_cents` of every draw request of the project still in status `DRAFT` are recomputed, because a held module leaves the work-in-progress basis entirely."
    PRD §3.4: "In every other case — a module still `PLANNED`, or any module under an agency hold — the earned value is 0."
    PRD §3.9: "The **substance test** second: `certified_basis_cents` must be strictly greater than 0, because a draw with no qualifying module work cannot be certified; a zero basis is `ERR_NO_CERTIFIABLE_WIP`."

    Design: Difficulty/transitive_cascade/qc_hold_cascade_depth_four_module_shipment_route_permit_and_draft_draw_basis
    """
    world, draw, reinspection = overwide_module_aboard_a_two_state_load
    assert_cents(draw["basis_earned_cents"], 8750000, "basis_earned_cents")
    assert_cents(draw["requested_cents"], 1750000, "requested_cents")

    validate_success(
        world.api.record_inspection_result(
            reinspection["id"],
            f.inspection_result_payload("FAIL", 3, 4),
            world.inspector,
        )
    )

    emptied = validate_success(world.api.get_draw_request(draw["id"], PROGRAM_ADMIN))
    assert emptied["basis_module_count"] == 0
    assert_cents(emptied["basis_earned_cents"], 0, "basis_earned_cents")
    assert_cents(emptied["requested_cents"], 0, "requested_cents")
    assert_cents(world.refresh_module()["wip_earned_cents"], 0, "wip_earned_cents")

    validate_error(
        world.api.certify_draw(
            draw["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR
        ),
        ERR_NO_CERTIFIABLE_WIP,
    )
