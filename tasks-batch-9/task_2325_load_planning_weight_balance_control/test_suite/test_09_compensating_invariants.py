"""Paired opposite operations that must return the ledger to where it started."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import CAPTAIN_1, LOAD_CONTROLLER, LOAD_CONTROLLER_1, api_client
from test_helpers import ApiErrorId as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import captain_headers, load_controller_headers

_SPECS = {spec["code"]: spec for spec in F.CANONICAL_COMPARTMENTS}


def _layout(*codes: str):
    return [_SPECS[code] for code in codes]


def _controller():
    return load_controller_headers(LOAD_CONTROLLER_1)


def _record(world: fx.Scenario, change_kind: str, code: str, **quantities):
    return api_client.create_last_minute_change(
        F.last_minute_change_payload(
            world.sheet_id, change_kind, world.compartment_id(code), **quantities
        ),
        _controller(),
    )


# ---------------------------------------------------------------------------
# Two passengers boarded and then walked off again
# ---------------------------------------------------------------------------


def _signed_sheet_world() -> fx.Scenario:
    """A workhorse flight whose sheet the commander has already accepted."""
    return fx.accepted_sheet_world(
        captain_headers(CAPTAIN_1), flight_overrides={"flight_number": "LX1740"}
    )


class TestPaxAddThenRemove:
    def test_the_boarding_pair_moves_both_the_net_and_the_absolute_total(self):
        """Two extra passengers aft push the weight and the index the same way.

        PRD: "For `PAX_ADD` the signed mass is positive and equals the male count
        multiplied by the flight's weight programme's `male_kg` plus the female
        count multiplied by `female_kg`; for `PAX_REMOVE` it is the negation of
        that same figure."

        Design: Difficulty/compensating_invariant/pax_add_then_remove_conserves_sheet_index_moment
        """
        world = _signed_sheet_world()
        A.assert_sheet_figures(
            world.sheet,
            issued_takeoff_weight_kg=58600.00,
            issued_index_tow=90.30,
            issued_payload_kg=6500.00,
            lmc_allowance_kg=500.00,
        )

        boarded = get_success_data(_record(world, "PAX_ADD", "OC", male_count=2), 201)

        A.assert_kg(boarded["weight_delta_kg"], 176.00, "weight_delta_kg")
        A.assert_index(boarded["index_delta"], 1.04, "index_delta")
        A.assert_sheet_figures(
            fx.refresh_sheet(world),
            lmc_net_weight_delta_kg=176.00,
            lmc_absolute_weight_delta_kg=176.00,
            final_takeoff_weight_kg=58776.00,
            final_index_tow=91.34,
            final_mac_tow_pct=16.75,
            final_payload_kg=6676.00,
        )

    def test_walking_the_pair_off_again_nets_to_nothing_but_spends_the_allowance_twice(self):
        """The signed totals return to zero while the absolute total keeps counting.

        PRD: "The allowance binds the absolute total, not the net one, which is
        the whole point: a 200-kilogram addition followed by a 200-kilogram
        removal nets to nothing but consumes 400 kilograms of allowance."

        Design: Difficulty/compensating_invariant/pax_add_then_remove_conserves_sheet_index_moment
        """
        world = _signed_sheet_world()
        get_success_data(_record(world, "PAX_ADD", "OC", male_count=2), 201)

        removed = get_success_data(_record(world, "PAX_REMOVE", "OC", male_count=2), 201)

        A.assert_kg(removed["weight_delta_kg"], -176.00, "weight_delta_kg")
        A.assert_index(removed["index_delta"], -1.04, "index_delta")
        A.assert_sheet_figures(
            fx.refresh_sheet(world),
            lmc_net_weight_delta_kg=0.00,
            lmc_absolute_weight_delta_kg=352.00,
            final_takeoff_weight_kg=58600.00,
            final_index_tow=90.30,
            final_mac_tow_pct=16.37,
            final_payload_kg=6500.00,
        )

    def test_the_amendment_freezes_the_restored_figures_and_the_spent_allowance(self):
        """The final record equals the issued snapshot even after two changes.

        PRD: "Both a sheet that carried a dozen last-minute changes and a sheet
        that carried none converge on `AMENDED`, and in the latter case the final
        figures simply equal the issued snapshots."

        Design: Difficulty/compensating_invariant/pax_add_then_remove_conserves_sheet_index_moment
        """
        world = _signed_sheet_world()
        get_success_data(_record(world, "PAX_ADD", "OC", male_count=2), 201)
        get_success_data(_record(world, "PAX_REMOVE", "OC", male_count=2), 201)
        fx.depart(world)

        amended = get_success_data(
            api_client.amend_load_sheet(world.sheet_id, _controller()), 200
        )

        A.assert_sheet_figures(
            amended,
            status="AMENDED",
            final_takeoff_weight_kg=58600.00,
            final_index_tow=90.30,
            final_mac_tow_pct=16.37,
            final_payload_kg=6500.00,
            lmc_absolute_weight_delta_kg=352.00,
        )
        A.assert_final_equals_issued(amended)
        A.assert_flight_state(fx.refresh_flight(world), status="DEPARTED")
        A.assert_plan_figures(
            fx.refresh_plan(world), base_payload_kg=6500.00, takeoff_weight_kg=58600.00
        )


# ---------------------------------------------------------------------------
# A change recorded, reversed, and the freed allowance spent again
# ---------------------------------------------------------------------------


def _live_sheet_world() -> fx.Scenario:
    """A workhorse flight with a sheet issued and still awaiting the flight deck."""
    return fx.issued_sheet_world(flight_overrides={"flight_number": "LX1750"})


class TestReversalRestoresAllowance:
    def test_a_bag_addition_consumes_its_share_of_the_allowance(self):
        """The first change spends 300 of the 500 kilograms the sheet granted.

        PRD: "Admission of a new change is tested *before* it is persisted — the
        sheet's current absolute total plus the absolute value of the new change's
        `weight_delta_kg` must be less than or equal to `lmc_allowance_kg`, and a
        violation is refused with `ERR_LMC_ALLOWANCE_EXCEEDED` with nothing
        written."

        Design: Difficulty/compensating_invariant/lmc_reverse_restores_allowance_consumption
        """
        world = _live_sheet_world()
        A.assert_sheet_figures(
            world.sheet,
            status="ISSUED",
            lmc_allowance_kg=500.00,
            lmc_absolute_weight_delta_kg=0.00,
            issued_takeoff_weight_kg=58600.00,
            issued_index_tow=90.30,
        )

        change = get_success_data(_record(world, "BAG_ADD", "H4", mass_kg=300), 201)

        A.assert_kg(change["weight_delta_kg"], 300.00, "weight_delta_kg")
        A.assert_index(change["index_delta"], 2.28, "index_delta")
        assert change["status"] == "APPLIED", "a recorded change should read APPLIED"
        A.assert_sheet_figures(
            fx.refresh_sheet(world),
            lmc_net_weight_delta_kg=300.00,
            lmc_absolute_weight_delta_kg=300.00,
            final_takeoff_weight_kg=58900.00,
            final_index_tow=92.58,
            final_mac_tow_pct=17.21,
            final_payload_kg=6800.00,
        )

    def test_reversal_returns_the_index_and_the_consumption_to_where_they_stood(self):
        """Recomputing from scratch undoes the consumption, not merely the net weight.

        PRD: "Because the absolute total is recomputed rather than merely
        decremented, reversing a change returns both the sheet's index position and
        its allowance consumption to where they stood before the change was
        recorded, freeing that allowance for a different adjustment."

        Design: Difficulty/compensating_invariant/lmc_reverse_restores_allowance_consumption
        """
        world = _live_sheet_world()
        change = get_success_data(_record(world, "BAG_ADD", "H4", mass_kg=300), 201)

        reversed_change = get_success_data(
            api_client.reverse_last_minute_change(str(change["id"]), _controller()), 200
        )

        assert reversed_change["status"] == "REVERSED", (
            "a reversed change should read REVERSED"
        )
        A.assert_sheet_figures(
            fx.refresh_sheet(world),
            lmc_net_weight_delta_kg=0.00,
            lmc_absolute_weight_delta_kg=0.00,
            final_takeoff_weight_kg=58600.00,
            final_index_tow=90.30,
            final_mac_tow_pct=16.37,
            final_payload_kg=6500.00,
        )

    def test_the_freed_allowance_pays_for_a_larger_change_and_no_more(self):
        """The whole 500 kilograms is available again, and 501 is not.

        PRD: "The sheet keeps two running totals over its changes in `APPLIED`
        status, accumulated in `created_at` ascending order; changes in `REVERSED`
        status contribute 0 to both."

        Design: Difficulty/compensating_invariant/lmc_reverse_restores_allowance_consumption
        """
        world = _live_sheet_world()
        first = get_success_data(_record(world, "BAG_ADD", "H4", mass_kg=300), 201)
        get_success_data(
            api_client.reverse_last_minute_change(str(first["id"]), _controller()), 200
        )

        second = get_success_data(_record(world, "BAG_ADD", "H4", mass_kg=500), 201)

        A.assert_kg(second["weight_delta_kg"], 500.00, "weight_delta_kg")
        A.assert_index(second["index_delta"], 3.80, "index_delta")
        A.assert_sheet_figures(
            fx.refresh_sheet(world),
            lmc_absolute_weight_delta_kg=500.00,
            final_takeoff_weight_kg=59100.00,
            final_index_tow=94.10,
            final_mac_tow_pct=17.77,
            final_payload_kg=7000.00,
        )
        validate_error(
            _record(world, "BAG_ADD", "H4", mass_kg=1), E.LMC_ALLOWANCE_EXCEEDED, 422
        )
        rows, meta = validate_paginated(
            api_client.list_last_minute_changes(
                LOAD_CONTROLLER, {"load_sheet_id": world.sheet_id}
            )
        )
        A.assert_pagination_meta(meta, total_count=2)
        rows, meta = validate_paginated(
            api_client.list_last_minute_changes(
                LOAD_CONTROLLER, {"load_sheet_id": world.sheet_id, "status": "APPLIED"}
            )
        )
        A.assert_pagination_meta(meta, total_count=1)


# ---------------------------------------------------------------------------
# A line added, computed, deleted and computed again
# ---------------------------------------------------------------------------

def _revision_world() -> fx.Scenario:
    """A computed plan over one cabin zone and one small hold, per-line rounded."""
    world = fx.reference_world(
        compartment_specs=_layout("OB", "OC", "H5"), band_specs=[F.CANONICAL_BANDS[1]]
    )
    fx.plan_world(
        world,
        flight_overrides={"flight_number": "LX1760"},
        rounding_mode="PER_LINE_THEN_SUM",
    )
    fx.seat(world, "OC", male_count=50, child_count=6, infant_count=4)
    fx.stow_bags(world, "H5", 48, 625)
    fx.compute_plan(world)
    return world


def _baseline_figures(plan) -> None:
    A.assert_plan_figures(
        plan,
        status="COMPUTED",
        base_payload_kg=5275.00,
        index_zfw=97.10,
        zero_fuel_weight_kg=47825.00,
        mac_zfw_pct=23.45,
        takeoff_weight_kg=57375.00,
        index_tow=105.70,
        mac_tow_pct=23.11,
        underload_kg=14905.00,
        envelope_ok=True,
    )


class TestPlanRevisionCycle:
    def test_a_further_line_knocks_the_computation_back_to_draft(self):
        """The new line invalidates every derived figure the plan published.

        PRD: "The plan is returned from `COMPUTED` to `DRAFT`, every computed
        balance field on it is reset to 0 with `envelope_ok` reset to false, and
        the flight is walked back from `LOAD_CONTROLLED` to `PLANNING`."

        Design: Difficulty/compensating_invariant/plan_revision_cycle_conserves_base_payload_and_index
        """
        world = _revision_world()
        _baseline_figures(world.plan)

        fx.seat(world, "OB", male_count=40)

        invalidated = fx.refresh_plan(world)
        A.assert_plan_is_reset_to_draft(invalidated)
        A.assert_plan_figures(invalidated, envelope_ok=False)
        A.assert_flight_state(fx.refresh_flight(world), status="PLANNING")

    def test_the_second_computation_absorbs_the_new_line(self):
        """Recomputing folds the forward zone into a heavier, different balance.

        PRD: "Alongside the mass, each line publishes `index_delta`: the line
        weight multiplied by the difference between the compartment's `arm_m` and
        the airframe's `ref_arm_m`, divided by `index_c`, rounded half-up to 2
        decimals."

        Design: Difficulty/compensating_invariant/plan_revision_cycle_conserves_base_payload_and_index
        """
        world = _revision_world()
        added = fx.seat(world, "OB", male_count=40)
        A.assert_kg(added["line_weight_kg"], 3520.00, "line_weight_kg")
        A.assert_index(added["index_delta"], 2.82, "index_delta")

        recomputed = fx.compute_plan(world)

        A.assert_plan_figures(
            recomputed,
            status="COMPUTED",
            base_payload_kg=8795.00,
            index_zfw=99.92,
            zero_fuel_weight_kg=51345.00,
            mac_zfw_pct=23.15,
            takeoff_weight_kg=60895.00,
            index_tow=108.52,
            mac_tow_pct=22.88,
            underload_kg=11385.00,
            envelope_ok=True,
        )

    def test_deleting_the_line_and_recomputing_restores_every_baseline_figure(self):
        """A full lap of the revision loop leaves the plan exactly as it began.

        PRD: "A line may be removed from a plan that has not been sheeted;
        removal deletes the row outright, so a deleted line contributes nothing to
        any later computation."

        Design: Difficulty/compensating_invariant/plan_revision_cycle_conserves_base_payload_and_index
        """
        world = _revision_world()
        fx.seat(world, "OB", male_count=40)
        fx.compute_plan(world)

        removal = api_client.delete_pax_line(world.pax_line_id("OB"), LOAD_CONTROLLER)

        assert removal.status_code == 204, (
            f"deleting a passenger line should return 204 but returned {removal.status_code}"
        )
        A.assert_plan_figures(fx.refresh_plan(world), status="DRAFT")
        A.assert_flight_state(fx.refresh_flight(world), status="PLANNING")
        _baseline_figures(fx.compute_plan(world))
        rows, meta = validate_paginated(
            api_client.list_pax_lines(LOAD_CONTROLLER, {"load_plan_id": world.plan_id})
        )
        A.assert_pagination_meta(meta, total_count=1)
        A.assert_flight_state(fx.refresh_flight(world), status="LOAD_CONTROLLED")
