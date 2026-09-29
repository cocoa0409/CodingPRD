"""Requests that violate two rules at once and must report the earlier one."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ADMIN, CAPTAIN_1, LOAD_CONTROLLER, LOAD_CONTROLLER_1
from test_helpers import ApiErrorId as E
from test_helpers import api_client
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import captain_headers, load_controller_headers

_SPECS = {spec["code"]: spec for spec in F.CANONICAL_COMPARTMENTS}


def _layout(*codes: str):
    return [_SPECS[code] for code in codes]


# ---------------------------------------------------------------------------
# Sheet state (rung 11) outranks the allowance ceiling (rung 36)
# ---------------------------------------------------------------------------


def _rejected_sheet_world() -> fx.Scenario:
    """A workhorse flight whose first sheet the commander turned down."""
    world = fx.workhorse_world(flight_overrides={"flight_number": "LX1634"})
    fx.issue_sheet(world, load_controller_headers(LOAD_CONTROLLER_1))
    world.sheet = get_success_data(
        api_client.reject_load_sheet(world.sheet_id, captain_headers(CAPTAIN_1))
    )
    return world


def _oversized_change(world: fx.Scenario, sheet_id: str):
    return api_client.create_last_minute_change(
        F.last_minute_change_payload(
            sheet_id, "BAG_ADD", world.compartment_id("H4"), mass_kg=5000
        ),
        load_controller_headers(LOAD_CONTROLLER_1),
    )


class TestSheetStateBeatsAllowance:
    def test_a_rejected_sheet_reports_its_state_rather_than_the_allowance(self):
        """An over-allowance change on a rejected sheet reports the sheet state.

        PRD: "Load-sheet state — `ERR_SHEET_INVALID_STATE`, 409, on sheet
        acceptance, sheet rejection, sheet amendment, and last-minute-change
        recording; recording a change requires the sheet to be `ISSUED` or
        `ACCEPTED`."

        Design: Difficulty/priority_pair_validation_conflict/sheet_state_beats_lmc_allowance
        """
        world = _rejected_sheet_world()

        response = _oversized_change(world, world.sheet_id)

        validate_error(response, E.SHEET_INVALID_STATE, 409)
        rejected = fx.refresh_sheet(world)
        A.assert_sheet_figures(
            rejected,
            status="REJECTED_BY_CAPTAIN",
            lmc_allowance_kg=500.00,
            lmc_absolute_weight_delta_kg=0.00,
        )

    def test_the_same_change_on_a_live_sheet_reports_the_allowance(self):
        """Once the state check passes, the allowance check is the one that bites.

        PRD: "Last-minute-change allowance — `ERR_LMC_ALLOWANCE_EXCEEDED`, 422,
        on last-minute-change recording."

        Design: Difficulty/priority_pair_validation_conflict/sheet_state_beats_lmc_allowance
        """
        world = _rejected_sheet_world()
        reissued = fx.issue_sheet(world, load_controller_headers(LOAD_CONTROLLER_1))
        A.assert_sheet_figures(
            reissued, status="ISSUED", sheet_no=2, lmc_allowance_kg=500.00
        )

        response = _oversized_change(world, str(reissued["id"]))

        validate_error(response, E.LMC_ALLOWANCE_EXCEEDED, 422)
        A.assert_sheet_figures(
            fx.refresh_sheet(world), lmc_absolute_weight_delta_kg=0.00
        )


# ---------------------------------------------------------------------------
# Compartment kind (rung 17) outranks seat capacity (rung 27)
# ---------------------------------------------------------------------------


def _cabin_and_hold_plan() -> fx.Scenario:
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H1"), band_specs=[F.CANONICAL_BANDS[1]]
    )
    return fx.plan_world(world, flight_overrides={"flight_number": "LX1636"})


class TestCompartmentKindBeatsSeatCapacity:
    def test_seating_passengers_in_a_hold_reports_the_kind_mismatch(self):
        """A hold has no seats at all, and the kind check fires before the count.

        PRD: "Compartment kind matches its use — a `CABIN_ZONE` compartment is
        required for a passenger line and for `PAX_ADD` or `PAX_REMOVE` changes;
        a `HOLD` compartment is required for a bag allocation, a consignment
        stowage, a gate bag and `BAG_ADD`, `BAG_REMOVE` or `CARGO_OFFLOAD`
        changes."

        Design: Difficulty/priority_pair_validation_conflict/paxline_compartment_kind_beats_seat_capacity
        """
        world = _cabin_and_hold_plan()

        response = api_client.create_pax_line(
            F.pax_line_payload(world.plan_id, world.compartment_id("H1"), male_count=40),
            LOAD_CONTROLLER,
        )

        validate_error(response, E.COMPARTMENT_KIND_MISMATCH, 422)

    def test_overfilling_a_cabin_zone_reports_the_seat_capacity(self):
        """With the right kind of compartment the capacity check is what refuses.

        PRD: "Seat capacity — `ERR_SEAT_CAPACITY_EXCEEDED`, 422, on
        passenger-line creation."

        Design: Difficulty/priority_pair_validation_conflict/paxline_compartment_kind_beats_seat_capacity
        """
        world = _cabin_and_hold_plan()

        response = api_client.create_pax_line(
            F.pax_line_payload(world.plan_id, world.compartment_id("OC"), male_count=61),
            LOAD_CONTROLLER,
        )

        validate_error(response, E.SEAT_CAPACITY_EXCEEDED, 422)

    def test_a_legal_mix_is_accepted_and_neither_refusal_left_a_row(self):
        """The two refusals persisted nothing, so the plan holds exactly one line.

        PRD: "Seats are consumed by adults and seated children only — the sum of
        `male_count`, `female_count` and `child_count` must not exceed the
        compartment's `seat_capacity`, or the line is refused with
        `ERR_SEAT_CAPACITY_EXCEEDED` — while `infant_count` is excluded from that
        sum entirely, because a lap infant occupies no seat."

        Design: Difficulty/priority_pair_validation_conflict/paxline_compartment_kind_beats_seat_capacity
        """
        world = _cabin_and_hold_plan()
        validate_error(
            api_client.create_pax_line(
                F.pax_line_payload(world.plan_id, world.compartment_id("H1"), male_count=40),
                LOAD_CONTROLLER,
            ),
            E.COMPARTMENT_KIND_MISMATCH,
            422,
        )
        validate_error(
            api_client.create_pax_line(
                F.pax_line_payload(world.plan_id, world.compartment_id("OC"), male_count=61),
                LOAD_CONTROLLER,
            ),
            E.SEAT_CAPACITY_EXCEEDED,
            422,
        )

        line = get_success_data(
            api_client.create_pax_line(
                F.pax_line_payload(
                    world.plan_id,
                    world.compartment_id("OC"),
                    male_count=50,
                    child_count=6,
                    infant_count=4,
                ),
                LOAD_CONTROLLER,
            ),
            201,
        )

        A.assert_kg(line["line_weight_kg"], 4650.00, "line_weight_kg")
        rows, meta = validate_paginated(
            api_client.list_pax_lines(LOAD_CONTROLLER, {"load_plan_id": world.plan_id})
        )
        A.assert_pagination_meta(meta, total_count=1)
        A.assert_plan_figures(fx.refresh_plan(world), status="DRAFT")


# ---------------------------------------------------------------------------
# Reference-data posture (rung 7) outranks the runway slot (rung 33)
# ---------------------------------------------------------------------------


def _slot_bound_world():
    """A single-slot runway whose 10:00 window is already taken, and two programmes."""
    fx.position_clock()
    airframes = [fx.create_aircraft(reg) for reg in ("HB-AAA", "HB-BBB", "HB-CCC")]
    runway = fx.create_runway(designator="26", slot_capacity_per_window=1)
    fx.create_performance_bands(str(runway["id"]), [F.CANONICAL_BANDS[1]])
    active = fx.create_weight_program()
    withdrawn = fx.create_weight_program(
        code="OLD-2019", male_kg=84.0, female_kg=66.0, documentation_ref="OM-A 8.1.3 rev 4"
    )
    validate_success(api_client.withdraw_weight_program(str(withdrawn["id"]), ADMIN), 200)

    fx.create_flight(
        str(airframes[0]["id"]),
        str(runway["id"]),
        str(active["id"]),
        flight_number="LX1640",
    )
    return airframes, runway, active, withdrawn


def _request_flight(aircraft, runway, program, **overrides):
    return api_client.create_flight(
        F.flight_payload(str(aircraft["id"]), str(runway["id"]), str(program["id"]), **overrides),
        LOAD_CONTROLLER,
    )


class TestProgrammePostureBeatsRunwaySlot:
    def test_a_withdrawn_programme_is_reported_before_the_full_slot(self):
        """Two rules are broken at once and the posture check is heard first.

        PRD: "Reference-data posture at flight creation —
        `ERR_AIRCRAFT_GROUNDED`, `ERR_RUNWAY_CLOSED` or
        `ERR_WEIGHT_PROGRAM_WITHDRAWN`, 409."

        Design: Difficulty/priority_pair_validation_conflict/program_withdrawn_beats_runway_slot_full
        """
        airframes, runway, _, withdrawn = _slot_bound_world()

        response = _request_flight(
            airframes[1],
            runway,
            withdrawn,
            flight_number="LX1642",
            scheduled_off_block_utc="2026-08-15T10:05:00Z",
            scheduled_on_block_utc="2026-08-15T12:35:00Z",
        )

        validate_error(response, E.WEIGHT_PROGRAM_WITHDRAWN, 409)
        stored = get_success_data(api_client.get_weight_program(str(withdrawn["id"]), ADMIN))
        assert stored["status"] == "WITHDRAWN", "the withdrawn programme should read WITHDRAWN"

    def test_an_active_programme_in_the_same_window_reports_the_full_slot(self):
        """With a healthy programme the slot ceiling is the rule that refuses.

        PRD: "Runway departure slot capacity — `ERR_RUNWAY_SLOT_FULL`, 409, on
        flight creation."

        Design: Difficulty/priority_pair_validation_conflict/program_withdrawn_beats_runway_slot_full
        """
        airframes, runway, active, _ = _slot_bound_world()

        response = _request_flight(
            airframes[2],
            runway,
            active,
            flight_number="LX1644",
            scheduled_off_block_utc="2026-08-15T10:05:00Z",
            scheduled_on_block_utc="2026-08-15T12:35:00Z",
        )

        validate_error(response, E.RUNWAY_SLOT_FULL, 409)

    def test_the_next_window_opens_and_only_the_admitted_flights_persist(self):
        """A departure on the next boundary is admitted; the two refusals wrote nothing.

        PRD: "A departure standing exactly on the next 10-minute boundary belongs
        to the following window and never collides with the current one."

        Design: Difficulty/priority_pair_validation_conflict/program_withdrawn_beats_runway_slot_full
        """
        airframes, runway, active, withdrawn = _slot_bound_world()
        validate_error(
            _request_flight(
                airframes[1], runway, withdrawn,
                flight_number="LX1642",
                scheduled_off_block_utc="2026-08-15T10:05:00Z",
                scheduled_on_block_utc="2026-08-15T12:35:00Z",
            ),
            E.WEIGHT_PROGRAM_WITHDRAWN,
            409,
        )
        validate_error(
            _request_flight(
                airframes[2], runway, active,
                flight_number="LX1644",
                scheduled_off_block_utc="2026-08-15T10:05:00Z",
                scheduled_on_block_utc="2026-08-15T12:35:00Z",
            ),
            E.RUNWAY_SLOT_FULL,
            409,
        )

        admitted = get_success_data(
            _request_flight(
                airframes[2], runway, active,
                flight_number="LX1646",
                scheduled_off_block_utc="2026-08-15T10:10:00Z",
                scheduled_on_block_utc="2026-08-15T12:40:00Z",
            ),
            201,
        )

        A.assert_flight_capacity(
            admitted, allowed_payload_kg=20180.00, limiting_factor="MZFW"
        )
        rows, meta = validate_paginated(
            api_client.list_flights(LOAD_CONTROLLER, {"departure_runway_id": str(runway["id"])})
        )
        A.assert_pagination_meta(meta, total_count=2)
