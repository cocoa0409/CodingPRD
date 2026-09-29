"""Lifecycle transitions, their side effects and the refusals that guard them."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    CAPTAIN_1,
    CAPTAIN_2,
    DG_OFFICER_1,
    LOAD_CONTROLLER,
    LOAD_CONTROLLER_1,
    RAMP_AGENT,
    api_client,
)
from test_helpers import ApiErrorId as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import captain_headers, dg_officer_headers, load_controller_headers

_SPECS = {spec["code"]: spec for spec in F.CANONICAL_COMPARTMENTS}


def _layout(*codes: str):
    return [_SPECS[code] for code in codes]


def _controller():
    return load_controller_headers(LOAD_CONTROLLER_1)


# ---------------------------------------------------------------------------
# Where every machine starts
# ---------------------------------------------------------------------------


def _hold_only_flight(flight_number: str, *codes: str) -> fx.Scenario:
    """A flight over a minimal hold-only layout, with no plan open on it."""
    world = fx.reference_world(
        compartment_specs=_layout(*(codes or ("H4",))), band_specs=[F.CANONICAL_BANDS[1]]
    )
    return fx.flight_world(world, flight_number=flight_number)


class TestInitialStates:
    def test_a_new_flight_opens_in_planning_with_its_release_open(self):
        """Both flight dimensions and the hold ledger start at their zero point.

        PRD: "The flight is created with `status` `PLANNING`, `load_release_state`
        `OPEN` and `dg_hold_count` 0."

        Design: Corner/state_machines/initial_states_flight_planning_open_and_dangerous_goods_cargo_booked
        """
        world = _hold_only_flight("LX1602")

        A.assert_flight_state(
            world.flight, status="PLANNING", load_release_state="OPEN", dg_hold_count=0
        )
        A.assert_version_is(world.flight, 1, "flight")

    def test_a_dangerous_goods_consignment_is_booked_unstowed_and_ranked_second(self):
        """Flagging the consignment denies it the ordinary automatic acceptance.

        PRD: "Everything else is created in `BOOKED` status and must be accepted
        explicitly."

        Design: Corner/state_machines/initial_states_flight_planning_open_and_dangerous_goods_cargo_booked
        """
        world = _hold_only_flight("LX1602")

        response = api_client.create_cargo_item(
            F.cargo_item_payload(
                world.flight_id,
                "724-30000001",
                item_kind="GENERAL",
                weight_kg=400,
                length_m=1.2,
                is_dangerous_goods=True,
            ),
            RAMP_AGENT,
        )

        booked = get_success_data(response, 201)
        A.assert_cargo_state(
            booked,
            status="BOOKED",
            assigned_compartment_id=None,
            item_kind="GENERAL",
            offload_priority_rank=2,
        )
        assert booked["is_dangerous_goods"] is True, (
            "the dangerous-goods flag should round-trip on the booked consignment"
        )
        A.assert_version_is(booked, 1, "consignment")


# ---------------------------------------------------------------------------
# The compute transition and everything it drags along
# ---------------------------------------------------------------------------


class TestComputeSideEffects:
    def test_one_compute_call_moves_both_rows_and_both_state_machines(self):
        """The per-row figures, the whole balance chain and two states in one call.

        PRD: "When the base payload fits — the frozen underload is 0 or positive —
        and the envelope verdict is true, the plan moves `DRAFT` → `COMPUTED`, and
        as the third hop of the same operation the flight moves `PLANNING` →
        `LOAD_CONTROLLED` with its `version` incremented by 1."

        Design: Corner/state_machines/compute_side_effects_move_plan_to_computed_and_flight_to_load_controlled
        """
        world = fx.fx_a(flight_overrides={"flight_number": "LX1602"})

        computed = fx.compute_plan(world)

        line = get_success_data(
            api_client.get_pax_line(world.pax_line_id("OC"), LOAD_CONTROLLER)
        )
        A.assert_kg(line["line_weight_kg"], 4650.00, "line_weight_kg")
        A.assert_index(line["index_delta"], 27.44, "index_delta")
        allocation = get_success_data(
            api_client.get_bag_allocation(world.bag_allocation_id("H1"), LOAD_CONTROLLER)
        )
        A.assert_kg(allocation["effective_weight_kg"], 1450.00, "effective_weight_kg")
        A.assert_index(allocation["index_delta"], -11.31, "index_delta")
        A.assert_plan_figures(
            computed,
            status="COMPUTED",
            restriction_status="UNRESTRICTED",
            base_payload_kg=6100.00,
            frozen_underload_kg=14080.00,
            planned_payload_kg=6100.00,
            zero_fuel_weight_kg=48650.00,
            index_zfw=78.66,
            mac_zfw_pct=14.03,
            takeoff_weight_kg=58200.00,
            index_tow=87.26,
            mac_tow_pct=15.24,
            taxi_weight_kg=58450.00,
            landing_weight_kg=51300.00,
            underload_kg=14080.00,
            envelope_ok=True,
        )
        A.assert_version_is(computed, 2, "load plan")
        A.assert_flight_state(fx.refresh_flight(world), status="LOAD_CONTROLLED")


# ---------------------------------------------------------------------------
# Transitions the ladder refuses outright
# ---------------------------------------------------------------------------


class TestDepartFromPlanning:
    def test_departure_before_load_control_reports_the_flight_state(self):
        """Departure is defined only from load control, so planning is refused.

        PRD: "`PLANNING` is required to compute a plan and to apply an offload;
        `PLANNING` or `LOAD_CONTROLLED` is required to create a plan, create a
        passenger line, create a bag allocation, book a consignment, accept a
        consignment, stow a consignment and cancel a flight; `LOAD_CONTROLLED` is
        required to record departure; `DEPARTED` is required to close a flight and
        to amend a sheet; and `LOAD_CONTROLLED`, `DEPARTED` or `CLOSED` is required
        to open a load audit."

        Design: Corner/state_machines/depart_from_planning_rejected_as_invalid_flight_state
        """
        world = _hold_only_flight("LX1602")

        response = api_client.depart_flight(world.flight_id, LOAD_CONTROLLER)

        validate_error(response, E.FLIGHT_INVALID_STATE, 409)
        still_planning = fx.refresh_flight(world)
        A.assert_flight_state(
            still_planning, status="PLANNING", load_release_state="OPEN"
        )
        A.assert_version_is(still_planning, 1, "flight")


class TestClosedFlightLockdown:
    def test_a_closed_flight_refuses_cancellation_and_keeps_every_row_where_it_was(self):
        """Nothing reopens a closed flight, so no cancel side effect may fire.

        PRD: "`CLOSED` and `CANCELLED` are the two terminal states of the flight
        planning lifecycle, and no operation moves a flight out of either."

        Design: Corner/state_machines/cancel_of_a_closed_flight_rejected_terminal_state_lockdown
        """
        world = fx.departed_sheet_world(flight_overrides={"flight_number": "LX1602"})
        closed = get_success_data(api_client.close_flight(world.flight_id, ADMIN), 200)
        A.assert_flight_state(closed, status="CLOSED")
        closed_version = int(closed["version"])

        response = api_client.cancel_flight(world.flight_id, ADMIN)

        validate_error(response, E.FLIGHT_INVALID_STATE, 409)
        A.assert_flight_state(fx.refresh_flight(world), status="CLOSED")
        A.assert_version_is(fx.refresh_flight(world), closed_version, "flight")
        A.assert_plan_figures(fx.refresh_plan(world), status="SHEET_ISSUED")
        A.assert_sheet_figures(fx.refresh_sheet(world), status="ACCEPTED")


class TestRepeatAcceptance:
    def test_a_second_commander_cannot_accept_an_already_accepted_sheet(self):
        """Acceptance is a one-way transition, not an idempotent write.

        PRD: "Load-sheet state — `ERR_SHEET_INVALID_STATE`, 409, on sheet
        acceptance, sheet rejection, sheet amendment, and last-minute-change
        recording; recording a change requires the sheet to be `ISSUED` or
        `ACCEPTED`."

        Design: Corner/state_machines/second_acceptance_of_the_same_load_sheet_rejected_idempotency
        """
        world = fx.accepted_sheet_world(
            captain_headers(CAPTAIN_1), flight_overrides={"flight_number": "LX1602"}
        )
        signed_version = int(world.sheet["version"])

        response = api_client.accept_load_sheet(world.sheet_id, captain_headers(CAPTAIN_2))

        validate_error(response, E.SHEET_INVALID_STATE, 409)
        unchanged = fx.refresh_sheet(world)
        A.assert_sheet_figures(
            unchanged, status="ACCEPTED", accepted_by_user_id=CAPTAIN_1
        )
        A.assert_version_is(unchanged, signed_version, "load sheet")
        A.assert_flight_state(fx.refresh_flight(world), load_release_state="RELEASED")


class TestDepartWithoutRelease:
    def test_an_unsigned_sheet_leaves_the_load_unreleased(self):
        """The flight state is satisfied, so only the release dimension can refuse.

        PRD: "Departure requires `load_release_state` `RELEASED`; sheet acceptance
        requires `dg_hold_count` equal to 0."

        Design: Corner/state_machines/depart_without_a_released_load_precondition_enforced
        """
        world = fx.issued_sheet_world(flight_overrides={"flight_number": "LX1602"})

        response = api_client.depart_flight(world.flight_id, _controller())

        validate_error(response, E.LOAD_NOT_RELEASED, 409)
        A.assert_flight_state(
            fx.refresh_flight(world), status="LOAD_CONTROLLED", load_release_state="OPEN"
        )
        A.assert_sheet_figures(fx.refresh_sheet(world), status="ISSUED")


# ---------------------------------------------------------------------------
# The dangerous-goods hold ledger
# ---------------------------------------------------------------------------

_DG_1 = "724-30000001"
_DG_2 = "724-30000002"


def _declared_dg_world(flight_number: str, *pairs) -> fx.Scenario:
    """A flight carrying one stowed dangerous good per (awb, hold) pair."""
    codes = tuple(code for _, code in pairs)
    world = _hold_only_flight(flight_number, *codes)
    for awb, code in pairs:
        fx.book_and_stow_cargo(
            world, awb, code, item_kind="GENERAL", weight_kg=400, length_m=1.2,
            is_dangerous_goods=True,
        )
    return world


class TestDeclarationRejectionCascade:
    def test_one_rejection_moves_the_declaration_the_consignment_and_the_ledger(self):
        """Three rows change from a single refusal on the paperwork.

        PRD: "The declaration moves `SUBMITTED` → `REJECTED`, the parent
        consignment is walked from `BOOKED` to `REJECTED` with its
        `assigned_compartment_id` cleared, the flight's `dg_hold_count` is
        decremented by 1, and the flight's `version` is incremented by 1."

        Design: Corner/state_machines/declaration_rejection_cascades_the_consignment_to_rejected
        """
        world = _declared_dg_world("LX1602", (_DG_1, "H4"))
        fx.submit_declaration(world, _DG_1, 400)
        A.assert_flight_state(
            fx.refresh_flight(world), dg_hold_count=1, load_release_state="HELD_FOR_DG"
        )

        response = api_client.reject_hazmat_declaration(
            world.declaration_id(_DG_1), dg_officer_headers(DG_OFFICER_1)
        )

        rejected = get_success_data(response, 200)
        A.assert_declaration_state(rejected, status="REJECTED", notoc_issued=False)
        A.assert_cargo_state(
            fx.refresh_cargo(world, _DG_1), status="REJECTED", assigned_compartment_id=None
        )
        A.assert_flight_state(
            fx.refresh_flight(world), dg_hold_count=0, load_release_state="OPEN"
        )


class TestReleaseHoldClears:
    def test_the_hold_lifts_only_once_the_last_declaration_is_resolved(self):
        """One acceptance leaves the hold standing; the second resolution clears it.

        PRD: "In both directions, when the resolution takes `dg_hold_count` to 0 —
        that is, when the last outstanding declaration on the flight has been
        resolved either way — the flight's `load_release_state` returns from
        `HELD_FOR_DG` to `OPEN` and `dg_hold_count` reads 0."

        Design: Corner/state_machines/release_hold_clears_only_when_the_last_declaration_is_resolved
        """
        world = _declared_dg_world("LX1602", (_DG_1, "H4"), (_DG_2, "H5"))
        fx.submit_declaration(world, _DG_1, 400)
        fx.submit_declaration(
            world, _DG_2, 400, un_number="UN1789", imo_class="CLASS_8",
            segregation_group="CORROSIVE",
        )
        A.assert_flight_state(
            fx.refresh_flight(world), dg_hold_count=2, load_release_state="HELD_FOR_DG"
        )

        fx.accept_declaration(
            world.declaration_id(_DG_1), dg_officer_headers(DG_OFFICER_1)
        )
        A.assert_flight_state(
            fx.refresh_flight(world), dg_hold_count=1, load_release_state="HELD_FOR_DG"
        )
        validate_success(
            api_client.reject_hazmat_declaration(
                world.declaration_id(_DG_2), dg_officer_headers(DG_OFFICER_1)
            ),
            200,
        )

        A.assert_flight_state(
            fx.refresh_flight(world), dg_hold_count=0, load_release_state="OPEN"
        )
        A.assert_declaration_state(
            fx.refresh_declaration(world, _DG_1),
            status="ACCEPTED",
            accepted_by_user_id=DG_OFFICER_1,
        )
        A.assert_declaration_state(fx.refresh_declaration(world, _DG_2), status="REJECTED")
        A.assert_cargo_state(fx.refresh_cargo(world, _DG_1), status="BOOKED")
        A.assert_cargo_state(fx.refresh_cargo(world, _DG_2), status="REJECTED")


class TestDeclarationLedger:
    def test_each_submission_increments_the_count_and_re_enters_the_hold(self):
        """The second submission finds the hold already in force and stays there.

        PRD: "A further declaration submitted while a hold is already in force
        leaves `load_release_state` at `HELD_FOR_DG` — the state re-enters itself —
        increments `dg_hold_count` by 1 and increments the flight's `version` by 1
        again."

        Design: Corner/state_machines/declaration_submission_increments_the_flight_hold_ledger
        """
        world = _declared_dg_world("LX1602", (_DG_1, "H4"), (_DG_2, "H5"))
        before = fx.refresh_flight(world)
        A.assert_flight_state(before, dg_hold_count=0, load_release_state="OPEN")
        baseline_version = int(before["version"])

        first = fx.submit_declaration(world, _DG_1, 400)
        after_first = fx.refresh_flight(world)
        A.assert_flight_state(
            after_first, dg_hold_count=1, load_release_state="HELD_FOR_DG"
        )
        A.assert_version_is(after_first, baseline_version + 1, "flight")

        second = fx.submit_declaration(
            world, _DG_2, 400, un_number="UN1789", imo_class="CLASS_8",
            segregation_group="CORROSIVE",
        )

        after_second = fx.refresh_flight(world)
        A.assert_flight_state(
            after_second, dg_hold_count=2, load_release_state="HELD_FOR_DG"
        )
        A.assert_version_is(after_second, baseline_version + 2, "flight")
        for declaration in (first, second):
            A.assert_declaration_state(
                declaration, status="SUBMITTED", notoc_issued=False
            )
        rows, meta = validate_paginated(
            api_client.list_cargo_hazmat_declarations(world.cargo_id(_DG_1), RAMP_AGENT)
        )
        A.assert_pagination_meta(meta, total_count=1)


# ---------------------------------------------------------------------------
# The sheet, the captain and the ending of the flight
# ---------------------------------------------------------------------------


class TestCaptainRejection:
    def test_a_refused_sheet_walks_the_plan_back_to_computed(self):
        """The plan returns to computed with its figures intact and no cargo moved.

        PRD: "The sheet moves `ISSUED` → `REJECTED_BY_CAPTAIN` with its `version`
        incremented by 1, the parent plan is walked back `SHEET_ISSUED` →
        `COMPUTED` with its own `version` incremented by 1 so a corrected sheet can
        be issued, the flight's `load_release_state` is left exactly where it was at
        `OPEN`, and no consignment changes status."

        Design: Corner/state_machines/captain_rejection_returns_the_plan_to_computed
        """
        world = fx.fx_a_computed(flight_overrides={"flight_number": "LX1602"})
        fx.issue_sheet(world, _controller())

        response = api_client.reject_load_sheet(world.sheet_id, captain_headers(CAPTAIN_1))

        refused = get_success_data(response, 200)
        A.assert_sheet_figures(
            refused, status="REJECTED_BY_CAPTAIN", accepted_by_user_id=None
        )
        A.assert_plan_figures(
            fx.refresh_plan(world),
            status="COMPUTED",
            index_tow=87.26,
            planned_payload_kg=6100.00,
        )
        A.assert_flight_state(
            fx.refresh_flight(world), status="LOAD_CONTROLLED", load_release_state="OPEN"
        )


_CG_1 = "724-40000001"
_CG_2 = "724-40000002"
_CG_3 = "724-40000003"


def _sheeted_cargo_world(flight_number: str) -> fx.Scenario:
    """FX-A over three holds with one stowed consignment, plus a sheet issued."""
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H1", "H4"), band_specs=[F.CANONICAL_BANDS[1]]
    )
    fx.plan_world(world, flight_overrides={"flight_number": flight_number})
    fx.seat(world, "OC", male_count=25, female_count=35)
    fx.stow_bags(world, "H1", 112, 1450)
    fx.book_and_stow_cargo(
        world, _CG_1, "H4", item_kind="GENERAL", weight_kg=400, length_m=1.0
    )
    return world


class TestSheetAcceptanceCascade:
    def test_acceptance_loads_the_stowed_consignment_and_leaves_the_others(self):
        """Only the stowed, accepted consignment is loaded by the signature.

        PRD: "Then every consignment on the flight in `ACCEPTED` status with an
        `assigned_compartment_id` set transitions to `LOADED` with its own
        `version` incremented by 1, and for each of those consignments every
        declaration in `ACCEPTED` status has `notoc_issued` set to true — the
        paperwork record that the commander was notified of the dangerous goods
        aboard."

        Design: Corner/state_machines/sheet_acceptance_loads_only_the_stowed_accepted_consignments
        """
        world = _sheeted_cargo_world("LX1602")
        fx.book_cargo(world, _CG_2, item_kind="GENERAL", weight_kg=300, length_m=1.0)
        fx.book_cargo(world, _CG_3, item_kind="GATE_BAG", weight_kg=20, length_m=0.4)
        fx.compute_plan(world)
        fx.issue_sheet(world, _controller())

        signed = fx.accept_sheet(world, captain_headers(CAPTAIN_1))

        A.assert_sheet_figures(signed, status="ACCEPTED", accepted_by_user_id=CAPTAIN_1)
        assert signed["notoc_reference"] is None, (
            "a flight with no dangerous goods should leave notoc_reference absent"
        )
        A.assert_flight_state(fx.refresh_flight(world), load_release_state="RELEASED")
        A.assert_cargo_state(fx.refresh_cargo(world, _CG_1), status="LOADED")
        A.assert_cargo_state(fx.refresh_cargo(world, _CG_2), status="ACCEPTED")
        A.assert_cargo_state(fx.refresh_cargo(world, _CG_3), status="BOOKED")
        A.assert_plan_figures(fx.refresh_plan(world), base_payload_kg=6500.00)


class TestFlightCancelCascade:
    def test_cancelling_a_load_controlled_flight_supersedes_and_offloads_downward(self):
        """One cancellation supersedes the plan and its sheet and offloads the cargo.

        PRD: "From `LOAD_CONTROLLED`, cancellation is permitted only while no sheet
        on any plan of the flight is `ACCEPTED`; it then transitions every plan
        whose `status` is `DRAFT`, `COMPUTED`, `RESTRICTED` or `SHEET_ISSUED` to
        `SUPERSEDED`, transitions every sheet on those plans whose `status` is
        `ISSUED` or `REJECTED_BY_CAPTAIN` to `SUPERSEDED`, transitions every
        consignment whose `status` is `BOOKED`, `ACCEPTED` or `LOADED` to
        `OFFLOADED` with `assigned_compartment_id` cleared, and increments the
        flight's `version` by 1."

        Design: Corner/state_machines/flight_cancel_cascades_plans_sheets_and_cargo_downward
        """
        world = _sheeted_cargo_world("LX1602")
        fx.book_cargo(world, _CG_2, item_kind="GATE_BAG", weight_kg=20, length_m=0.4)
        validate_success(
            api_client.reject_cargo_item(world.cargo_id(_CG_2), RAMP_AGENT), 200
        )
        fx.compute_plan(world)
        fx.issue_sheet(world, _controller())

        response = api_client.cancel_flight(world.flight_id, ADMIN)

        cancelled = get_success_data(response, 200)
        A.assert_flight_state(cancelled, status="CANCELLED")
        A.assert_plan_figures(
            fx.refresh_plan(world), status="SUPERSEDED", base_payload_kg=6500.00
        )
        A.assert_sheet_figures(fx.refresh_sheet(world), status="SUPERSEDED")
        A.assert_cargo_state(
            fx.refresh_cargo(world, _CG_1), status="OFFLOADED", assigned_compartment_id=None
        )
        A.assert_cargo_state(fx.refresh_cargo(world, _CG_2), status="REJECTED")
