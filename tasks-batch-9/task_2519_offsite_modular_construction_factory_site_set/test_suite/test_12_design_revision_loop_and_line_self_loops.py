"""Two state machines that are not simple ladders.

A design revision can be pushed back to its author and re-enter review a second
time, and the segregation-of-duties check has to be evaluated against whoever
submitted it that time round. A module can be pulled back off the line and
re-slotted, and it loops on itself at every intermediate station before the last
one closes it out. Both graphs are walked around their backward edges here.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DESIGN_NOT_IN_REVIEW,
    ERR_SAME_ACTOR_REVIEW,
)
from test_helpers.assertions import assert_instant, assert_module_dimensions
from test_helpers.test_users import (
    DESIGN_ENGINEER_REVIEWER,
    DESIGN_ENGINEER_SUBMITTER,
)


@pytest.fixture
def revision_returned_for_rework(api):
    """R1 under review, then pushed back to its author.

    The revision is detailed to a compatibility score of 34 — five points of
    connection-detailing penalty, sixteen for two connection clashes and
    forty-five for nine uncoordinated field scope items — so it is nowhere near
    freezable as first drawn.
    """
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api,
        world.project_id,
        world.project["version"],
        connection_detail_state="FIELD_COORDINATED",
        open_connection_conflicts=2,
        field_scope_items_open=9,
    )
    submitted = validate_success(
        api.submit_design_package(
            world.package_id, f.submit_payload(), DESIGN_ENGINEER_SUBMITTER
        )
    )
    world.package = validate_success(
        api.decide_design_review(
            world.package_id,
            f.review_decision_payload(
                "RETURN_FOR_REVISION", review_note="coordinate the field scope first"
            ),
            DESIGN_ENGINEER_REVIEWER,
        )
    )
    return world, submitted


def test_a_returned_revision_reenters_review_with_a_higher_round_counter(
    revision_returned_for_rework,
):
    """PRD §3.2: "Submitting a revision for freeze review moves `freeze_state` from `DRAFT` to `IN_REVIEW`, and it is the same operation that closes the revision loop from `REVISION_REQUIRED` back to `IN_REVIEW`."
    PRD §3.2: "On success the package's `factory_compatibility_score` is recomputed, `revision_round` increases by 1 — which is what makes the two visits to `IN_REVIEW` in a revision cycle distinguishable, since the counter is 0 while a package has never been submitted — `submitted_by_user_id` is set to the submitting engineer's `X-User-ID`, and the package's `version` increments."
    PRD §3.2: "`RETURN_FOR_REVISION` moves `freeze_state` from `IN_REVIEW` to `REVISION_REQUIRED`."

    Design: Difficulty/non_linear_state_machine/design_freeze_state_revision_loop_reenters_in_review_under_segregation_of_duties
    """
    world, first_submit = revision_returned_for_rework

    assert first_submit["freeze_state"] == "IN_REVIEW"
    assert first_submit["revision_round"] == 1
    assert world.package["freeze_state"] == "REVISION_REQUIRED"
    assert world.package["revision_round"] == 1

    resubmitted = validate_success(
        world.api.submit_design_package(
            world.package_id,
            f.submit_payload(
                open_connection_conflicts=0,
                field_scope_items_open=2,
                connection_detail_state="COMPLETE",
            ),
            DESIGN_ENGINEER_SUBMITTER,
        )
    )

    assert resubmitted["freeze_state"] == "IN_REVIEW"
    assert resubmitted["revision_round"] == 2


def test_a_revision_awaiting_rework_cannot_be_frozen_where_it_stands(
    revision_returned_for_rework,
):
    """PRD §3.2: "A different `DesignEngineer` supplies a `decision` of either `FREEZE` or `RETURN_FOR_REVISION`, optionally with a `review_note`, and the package must be in `freeze_state` `IN_REVIEW` — otherwise `ERR_DESIGN_NOT_IN_REVIEW`."

    Design: Difficulty/non_linear_state_machine/design_freeze_state_revision_loop_reenters_in_review_under_segregation_of_duties
    """
    world, _ = revision_returned_for_rework

    validate_error(
        world.api.decide_design_review(
            world.package_id,
            f.review_decision_payload("FREEZE"),
            DESIGN_ENGINEER_REVIEWER,
        ),
        ERR_DESIGN_NOT_IN_REVIEW,
    )

    assert world.refresh_package()["freeze_state"] == "REVISION_REQUIRED"


def test_the_second_review_pass_still_bars_the_engineer_who_resubmitted_it(
    revision_returned_for_rework,
):
    """PRD §3.2: "The reviewing `X-User-ID` must differ from `submitted_by_user_id`, or the attempt is `ERR_SAME_ACTOR_REVIEW`."
    PRD §3.2: "It then clears `submitted_by_user_id` back to null, so that the next submit records a fresh submitter and the segregation check is evaluated against that fresh identity rather than the stale one."
    PRD §3.2: "On success, `reviewed_by_user_id` and `review_note` are recorded, the project's `phase` is re-derived — which lifts a project sitting at `PRECONSTRUCTION` to `DESIGN_FROZEN` when no module has yet reached the line — and both the package's `version` and the project's `version` increment."

    Design: Difficulty/non_linear_state_machine/design_freeze_state_revision_loop_reenters_in_review_under_segregation_of_duties
    """
    world, _ = revision_returned_for_rework
    validate_success(
        world.api.submit_design_package(
            world.package_id,
            f.submit_payload(
                open_connection_conflicts=0,
                field_scope_items_open=2,
                connection_detail_state="COMPLETE",
            ),
            DESIGN_ENGINEER_SUBMITTER,
        )
    )

    validate_error(
        world.api.decide_design_review(
            world.package_id,
            f.review_decision_payload("FREEZE"),
            DESIGN_ENGINEER_SUBMITTER,
        ),
        ERR_SAME_ACTOR_REVIEW,
    )

    frozen = validate_success(
        world.api.decide_design_review(
            world.package_id,
            f.review_decision_payload("FREEZE", review_note="coordination closed out"),
            DESIGN_ENGINEER_REVIEWER,
        )
    )

    assert frozen["freeze_state"] == "FROZEN"
    # Complete detailing with no clashes leaves only the two open field items.
    assert frozen["factory_compatibility_score"] == 90
    assert world.refresh_project()["phase"] == "DESIGN_FROZEN"


@pytest.fixture
def two_slotted_modules(api):
    """M-01 holding 14:00 onward and M-02 holding 16:00 onward on one line."""
    world = fx.world_with_module(api)
    fx.add_module(world, "M-02", 2)
    fx.schedule_slot(world, "M-01", "2026-09-02T14:00:00Z")
    fx.schedule_slot(world, "M-02", "2026-09-02T16:00:00Z")
    return world


def test_releasing_a_takt_window_walks_production_back_to_planned(two_slotted_modules):
    """PRD §3.4: "It moves `production_status` from `SLOTTED` back to `PLANNED`, subtracts exactly the module's `line_slot_minutes` from the plant's `committed_line_minutes` so the ledger returns to its pre-schedule value, increments the plant's `version`, clears `line_slot_start` and `line_slot_end` and sets `line_slot_minutes` to 0, re-derives the project's `phase`, and increments the module's and the project's `version`."

    Design: Difficulty/non_linear_state_machine/production_status_release_backward_edge_and_in_line_self_loop
    """
    world = two_slotted_modules
    assert world.refresh_factory()["committed_line_minutes"] == 1110

    released = validate_success(
        world.api.release_line_slot(
            world.module_id("M-01"),
            {"reason": "material shortage at station 1"},
            world.factory_manager,
        )
    )

    assert_module_dimensions(released, production_status="PLANNED")
    assert released["line_slot_start"] is None
    assert released["line_slot_end"] is None
    assert released["line_slot_minutes"] == 0
    # Only M-01's own 540 minutes came off; M-02 still holds its 570.
    assert world.refresh_factory()["committed_line_minutes"] == 570


def test_a_released_module_reclaims_the_line_at_the_congestion_it_now_sees(
    two_slotted_modules,
):
    """PRD §3.4: "Claiming a takt window moves `production_status` from `PLANNED` to `SLOTTED`, and the only payload field is `line_slot_start`, the instant at which the module wants the line."
    PRD §3.4: "The effective takt in minutes is the plant's `takt_minutes` plus 5 minutes for each concurrent module — a five-minute congestion penalty per module already on the line at that instant."

    Design: Difficulty/non_linear_state_machine/production_status_release_backward_edge_and_in_line_self_loop
    """
    world = two_slotted_modules
    validate_success(
        world.api.release_line_slot(
            world.module_id("M-01"),
            {"reason": "material shortage at station 1"},
            world.factory_manager,
        )
    )

    reslotted = validate_success(
        world.api.schedule_line_slot(
            world.module_id("M-01"),
            f.line_slot_payload("2026-09-02T16:00:00Z"),
            world.factory_manager,
        )
    )

    assert_module_dimensions(reslotted, production_status="SLOTTED")
    # M-02 is on the line at 16:00 now, so the second claim costs 95 per station.
    assert reslotted["line_slot_minutes"] == 570
    assert_instant(reslotted["line_slot_start"], "2026-09-02T16:00:00Z")


def test_station_advances_loop_in_line_until_the_last_station_closes_it_out(
    two_slotted_modules,
):
    """PRD §3.4: "The first advance from `SLOTTED` moves `production_status` to `IN_LINE`, increases `station_index` by `stations_advanced` capped at the plant's `station_count`, recomputes `wip_earned_cents`, re-derives the project's `phase` from `DESIGN_FROZEN` up to `IN_PRODUCTION`, and increments both the module's and the project's `version`."
    PRD §3.4: "An intermediate advance, where `station_index` plus `stations_advanced` remains strictly less than the plant's `station_count`, keeps `production_status` at `IN_LINE`, increases `station_index` by `stations_advanced`, recomputes `wip_earned_cents`, recomputes the `basis_earned_cents` and `requested_cents` of every draw request of the project still in status `DRAFT`, and increments the module's `version`."
    PRD §3.4: "A terminating advance, where `station_index` plus `stations_advanced` reaches or exceeds the plant's `station_count`, moves `production_status` to `LINE_COMPLETE`, sets `station_index` exactly to the plant's `station_count`, subtracts the module's `line_slot_minutes` from the plant's `committed_line_minutes` and increments the plant's `version` — the line is released, and the interval stays on the module as history while no longer occupying capacity — recomputes `wip_earned_cents`, which under the station-progress rule now yields the plant's full `wip_unit_value_cents`, recomputes the `basis_earned_cents` and `requested_cents` of the project's `DRAFT` draw requests, and increments the module's `version`."

    Design: Difficulty/non_linear_state_machine/production_status_release_backward_edge_and_in_line_self_loop
    """
    world = two_slotted_modules

    first = fx.advance_stations(world, "M-01", 1)
    assert_module_dimensions(first, production_status="IN_LINE")
    assert first["station_index"] == 1

    intermediate = fx.advance_stations(world, "M-01", 2)
    assert_module_dimensions(intermediate, production_status="IN_LINE")
    assert intermediate["station_index"] == 3

    terminating = fx.advance_stations(world, "M-01", 3)
    assert_module_dimensions(terminating, production_status="LINE_COMPLETE")
    assert terminating["station_index"] == 6

    # M-01 has left the line; only M-02's claim is still held against the plant.
    assert world.refresh_factory()["committed_line_minutes"] == 570
