"""Cyclic and branching paths through the flight, plan and sheet state machines."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    CAPTAIN_1,
    DG_OFFICER_1,
    LOAD_CONTROLLER,
    LOAD_CONTROLLER_1,
    api_client,
)
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import captain_headers, dg_officer_headers, load_controller_headers

_SPECS = {spec["code"]: spec for spec in F.CANONICAL_COMPARTMENTS}


def _layout(*codes: str):
    return [_SPECS[code] for code in codes]


# ---------------------------------------------------------------------------
# The dangerous-goods release cycle runs parallel to the planning lifecycle
# ---------------------------------------------------------------------------

_DG_ONE = "724-44440001"
_DG_TWO = "724-44440002"


def _dg_cycle_world() -> fx.Scenario:
    """A computed flight carrying two undeclared dangerous-goods consignments."""
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H1", "H4"), band_specs=[F.CANONICAL_BANDS[1]]
    )
    fx.plan_world(world, flight_overrides={"flight_number": "LX1620"})
    fx.seat(world, "OC", male_count=50, child_count=6, infant_count=4)
    fx.stow_bags(world, "H1", 112, 1450)
    fx.book_and_stow_cargo(
        world, _DG_ONE, "H4", item_kind="GENERAL", weight_kg=400, length_m=1.0,
        is_dangerous_goods=True,
    )
    fx.book_and_stow_cargo(
        world, _DG_TWO, "H4", item_kind="GENERAL", weight_kg=200, length_m=0.6,
        is_dangerous_goods=True,
    )
    fx.compute_plan(world)
    return world


class TestDangerousGoodsHoldCycle:
    def test_each_submission_holds_the_release_and_leaves_the_lifecycle_alone(self):
        """Two submissions drive the release dimension only, never the status one.

        PRD: "A further declaration submitted while a hold is already in force
        leaves `load_release_state` at `HELD_FOR_DG` — the state re-enters itself
        — increments `dg_hold_count` by 1 and increments the flight's `version`
        by 1 again."

        Design: Difficulty/non_linear_state_machine/flight_dg_hold_cycle_parallel_to_status
        """
        world = _dg_cycle_world()
        A.assert_flight_state(
            fx.refresh_flight(world),
            status="LOAD_CONTROLLED",
            load_release_state="OPEN",
            dg_hold_count=0,
        )

        fx.submit_declaration(world, _DG_ONE, 400)
        A.assert_flight_state(
            fx.refresh_flight(world),
            status="LOAD_CONTROLLED",
            load_release_state="HELD_FOR_DG",
            dg_hold_count=1,
        )

        fx.submit_declaration(
            world,
            _DG_TWO,
            200,
            un_number="UN1789",
            imo_class="CLASS_8",
            segregation_group="CORROSIVE",
        )
        A.assert_flight_state(
            fx.refresh_flight(world),
            status="LOAD_CONTROLLED",
            load_release_state="HELD_FOR_DG",
            dg_hold_count=2,
        )

    def test_the_hold_clears_only_once_the_last_declaration_is_resolved(self):
        """Resolving one of two declarations keeps the hold; resolving both lifts it.

        PRD: "In both directions, when the resolution takes `dg_hold_count` to 0
        — that is, when the last outstanding declaration on the flight has been
        resolved either way — the flight's `load_release_state` returns from
        `HELD_FOR_DG` to `OPEN` and `dg_hold_count` reads 0."

        Design: Difficulty/non_linear_state_machine/flight_dg_hold_cycle_parallel_to_status
        """
        world = _dg_cycle_world()
        fx.submit_declaration(world, _DG_ONE, 400)
        fx.submit_declaration(
            world,
            _DG_TWO,
            200,
            un_number="UN1789",
            imo_class="CLASS_8",
            segregation_group="CORROSIVE",
        )
        officer = dg_officer_headers(DG_OFFICER_1)

        fx.accept_declaration(world.declaration_id(_DG_ONE), officer)
        A.assert_flight_state(
            fx.refresh_flight(world), load_release_state="HELD_FOR_DG", dg_hold_count=1
        )

        fx.accept_declaration(world.declaration_id(_DG_TWO), officer)
        A.assert_flight_state(
            fx.refresh_flight(world),
            status="LOAD_CONTROLLED",
            load_release_state="OPEN",
            dg_hold_count=0,
        )

    def test_release_reaches_its_terminal_state_while_the_lifecycle_stands_still(self):
        """The commander's signature moves release to RELEASED, not the lifecycle.

        PRD: "The `load_release_state` dimension tracks release of the load
        through `OPEN`, `HELD_FOR_DG` and `RELEASED`, starts at `OPEN`, and has
        `RELEASED` as its only terminal state."

        Design: Difficulty/non_linear_state_machine/flight_dg_hold_cycle_parallel_to_status
        """
        world = _dg_cycle_world()
        officer = dg_officer_headers(DG_OFFICER_1)
        fx.submit_declaration(world, _DG_ONE, 400)
        fx.submit_declaration(
            world,
            _DG_TWO,
            200,
            un_number="UN1789",
            imo_class="CLASS_8",
            segregation_group="CORROSIVE",
        )
        fx.accept_declaration(world.declaration_id(_DG_ONE), officer)
        fx.accept_declaration(world.declaration_id(_DG_TWO), officer)
        fx.accept_cargo_item(world.cargo_id(_DG_ONE))
        fx.accept_cargo_item(world.cargo_id(_DG_TWO))

        fx.issue_sheet(world, load_controller_headers(LOAD_CONTROLLER_1))
        fx.accept_sheet(world, captain_headers(CAPTAIN_1))

        A.assert_flight_state(
            fx.refresh_flight(world), status="LOAD_CONTROLLED", load_release_state="RELEASED"
        )


# ---------------------------------------------------------------------------
# The plan revision cycle: COMPUTED back to DRAFT and forward again
# ---------------------------------------------------------------------------


def _revision_world() -> fx.Scenario:
    """A plan seated and bagged in the aft hold, ready for its first compute."""
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H1", "H5"), band_specs=[F.CANONICAL_BANDS[1]]
    )
    fx.plan_world(world, flight_overrides={"flight_number": "LX1622"})
    fx.seat(world, "OC", male_count=50, child_count=6, infant_count=4)
    fx.stow_bags(world, "H5", 48, 625)
    return world


class TestPlanRevisionCycle:
    def test_the_first_compute_advances_both_the_plan_and_the_flight(self):
        """DRAFT to COMPUTED carries the flight from PLANNING to LOAD_CONTROLLED.

        PRD: "When the base payload fits — the frozen underload is 0 or positive
        — and the envelope verdict is true, the plan moves `DRAFT` → `COMPUTED`,
        and as the third hop of the same operation the flight moves `PLANNING` →
        `LOAD_CONTROLLED` with its `version` incremented by 1."

        Design: Difficulty/non_linear_state_machine/load_plan_revision_cycle_computed_to_draft_to_computed
        """
        world = _revision_world()

        fx.compute_plan(world)

        A.assert_plan_figures(
            world.plan,
            status="COMPUTED",
            base_payload_kg=5275.00,
            index_zfw=97.10,
            mac_zfw_pct=23.45,
        )
        A.assert_flight_state(fx.refresh_flight(world), status="LOAD_CONTROLLED")

    def test_a_new_allocation_walks_the_plan_and_the_flight_back(self):
        """Adding an allocation to a computed plan invalidates it and reverts both rows.

        PRD: "The plan is returned from `COMPUTED` to `DRAFT`, every computed
        balance field on it is reset to 0 with `envelope_ok` reset to false, and
        the flight is walked back from `LOAD_CONTROLLED` to `PLANNING`."

        Design: Difficulty/non_linear_state_machine/load_plan_revision_cycle_computed_to_draft_to_computed
        """
        world = _revision_world()
        fx.compute_plan(world)

        fx.stow_bags(world, "H1", 112, 1450)

        A.assert_plan_is_reset_to_draft(fx.refresh_plan(world))
        A.assert_flight_state(fx.refresh_flight(world), status="PLANNING")

    def test_the_second_compute_reinstates_the_pair_on_the_new_distribution(self):
        """The loop closes: the revised distribution computes without a new revision.

        PRD: "The `DRAFT` → `COMPUTED` → `DRAFT` loop is the ordinary plan
        revision cycle and may repeat any number of times."

        Design: Difficulty/non_linear_state_machine/load_plan_revision_cycle_computed_to_draft_to_computed
        """
        world = _revision_world()
        fx.compute_plan(world)
        fx.stow_bags(world, "H1", 112, 1450)

        fx.compute_plan(world)

        A.assert_plan_figures(
            world.plan,
            status="COMPUTED",
            revision_no=1,
            base_payload_kg=6725.00,
            index_zfw=85.79,
            mac_zfw_pct=17.29,
            takeoff_weight_kg=58825.00,
            mac_tow_pct=17.97,
        )
        A.assert_flight_state(fx.refresh_flight(world), status="LOAD_CONTROLLED")


# ---------------------------------------------------------------------------
# The commander's branch: acceptance against rejection
# ---------------------------------------------------------------------------

_ACCEPT_AWB = "724-55550001"
_REJECT_AWB = "724-55550002"


def _sheet_branch_worlds():
    """Two identically loaded flights, each with a sheet awaiting a decision."""
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H1", "H4"), band_specs=[F.CANONICAL_BANDS[1]]
    )
    controller = load_controller_headers(LOAD_CONTROLLER_1)

    accepted = fx.Scenario(
        aircraft=world.aircraft,
        compartments=world.compartments,
        runway=world.runway,
        bands=world.bands,
        program=world.program,
    )
    rejected = fx.Scenario(
        aircraft=world.aircraft,
        compartments=world.compartments,
        runway=world.runway,
        bands=world.bands,
        program=world.program,
    )
    fx.flight_world(accepted, flight_number="LX1624")
    fx.flight_world(
        rejected,
        flight_number="LX1626",
        scheduled_off_block_utc="2026-08-15T14:00:00Z",
        scheduled_on_block_utc="2026-08-15T16:30:00Z",
    )

    for arm, awb in ((accepted, _ACCEPT_AWB), (rejected, _REJECT_AWB)):
        arm.plan = fx.open_plan(arm.flight_id)
        fx.seat(arm, "OC", male_count=50, child_count=6, infant_count=4)
        fx.stow_bags(arm, "H1", 112, 1450)
        fx.book_and_stow_cargo(arm, awb, "H4", item_kind="GENERAL", weight_kg=400, length_m=0.8)
        fx.compute_plan(arm)
        fx.issue_sheet(arm, controller)
    return accepted, rejected


class TestLoadSheetDecisionBranch:
    def test_acceptance_releases_the_load_and_loads_the_stowed_consignment(self):
        """The acceptance arm cascades across sheet, flight, plan and cargo.

        PRD: "Then every consignment on the flight in `ACCEPTED` status with an
        `assigned_compartment_id` set transitions to `LOADED` with its own
        `version` incremented by 1, and for each of those consignments every
        declaration in `ACCEPTED` status has `notoc_issued` set to true — the
        paperwork record that the commander was notified of the dangerous goods
        aboard."

        Design: Difficulty/non_linear_state_machine/load_sheet_branch_accept_vs_reject_divergent_side_effects
        """
        accepted, _ = _sheet_branch_worlds()

        fx.accept_sheet(accepted, captain_headers(CAPTAIN_1))

        A.assert_sheet_figures(
            accepted.sheet, status="ACCEPTED", accepted_by_user_id=CAPTAIN_1, sheet_no=1
        )
        A.assert_flight_state(fx.refresh_flight(accepted), load_release_state="RELEASED")
        A.assert_cargo_state(fx.refresh_cargo(accepted, _ACCEPT_AWB), status="LOADED")
        A.assert_plan_figures(fx.refresh_plan(accepted), status="SHEET_ISSUED")

    def test_rejection_walks_the_plan_back_and_touches_no_cargo(self):
        """The rejection arm reopens the plan and leaves the release where it was.

        PRD: "The sheet moves `ISSUED` → `REJECTED_BY_CAPTAIN` with its `version`
        incremented by 1, the parent plan is walked back `SHEET_ISSUED` →
        `COMPUTED` with its own `version` incremented by 1 so a corrected sheet
        can be issued, the flight's `load_release_state` is left exactly where it
        was at `OPEN`, and no consignment changes status."

        Design: Difficulty/non_linear_state_machine/load_sheet_branch_accept_vs_reject_divergent_side_effects
        """
        _, rejected = _sheet_branch_worlds()

        rejected.sheet = get_success_data(
            api_client.reject_load_sheet(rejected.sheet_id, captain_headers(CAPTAIN_1))
        )

        A.assert_sheet_figures(
            rejected.sheet, status="REJECTED_BY_CAPTAIN", accepted_by_user_id=None
        )
        A.assert_flight_state(fx.refresh_flight(rejected), load_release_state="OPEN")
        A.assert_cargo_state(fx.refresh_cargo(rejected, _REJECT_AWB), status="ACCEPTED")
        A.assert_plan_figures(fx.refresh_plan(rejected), status="COMPUTED")

    def test_both_arms_start_from_the_same_issued_snapshot(self):
        """The divergence is in the decision, not in what the sheets recorded.

        PRD: "`issued_takeoff_weight_kg`, `issued_index_tow` and
        `issued_payload_kg` capture the plan's `takeoff_weight_kg`, `index_tow`
        and `planned_payload_kg` as they stand at that instant, and
        `weight_program_documentation_ref` captures the flight's weight
        programme's `documentation_ref` for the audit trail."

        Design: Difficulty/non_linear_state_machine/load_sheet_branch_accept_vs_reject_divergent_side_effects
        """
        accepted, rejected = _sheet_branch_worlds()

        for sheet in (accepted.sheet, rejected.sheet):
            A.assert_sheet_figures(
                sheet,
                issued_takeoff_weight_kg=58600.00,
                issued_index_tow=90.30,
                issued_payload_kg=6500.00,
                lmc_allowance_kg=500.00,
            )

        fx.accept_sheet(accepted, captain_headers(CAPTAIN_1))
        rejected.sheet = get_success_data(
            api_client.reject_load_sheet(rejected.sheet_id, captain_headers(CAPTAIN_1))
        )
        assert accepted.sheet["status"] != rejected.sheet["status"], (
            "the two decisions should leave the sheets in different states"
        )
