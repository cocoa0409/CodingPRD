"""Writes on one entity gated by the state of a second, unrelated entity."""

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
    AUDIT_INSPECTOR,
    CAPTAIN_1,
    DG_OFFICER_1,
    LOAD_CONTROLLER,
    LOAD_CONTROLLER_1,
    api_client,
)
from test_helpers import ApiErrorId as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    audit_inspector_headers,
    captain_headers,
    dg_officer_headers,
    load_controller_headers,
)

_SPECS = {spec["code"]: spec for spec in F.CANONICAL_COMPARTMENTS}


def _layout(*codes: str):
    return [_SPECS[code] for code in codes]


# ---------------------------------------------------------------------------
# A load sheet depends on the dangerous-goods paperwork
# ---------------------------------------------------------------------------

_UNDECLARED_DG = "724-12340001"


def _undeclared_dg_world() -> fx.Scenario:
    """A computed plan whose flight carries one booked, undeclared dangerous good."""
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H1"), band_specs=[F.CANONICAL_BANDS[1]]
    )
    fx.plan_world(world, flight_overrides={"flight_number": "LX1690"})
    fx.seat(world, "OC", male_count=50, child_count=6, infant_count=4)
    fx.stow_bags(world, "H1", 112, 1450)
    fx.book_cargo(
        world, _UNDECLARED_DG, item_kind="GENERAL", weight_kg=400, length_m=0.8,
        is_dangerous_goods=True,
    )
    fx.submit_declaration(world, _UNDECLARED_DG, 400)
    fx.compute_plan(world)
    return world


def _issue(world: fx.Scenario, plan_version: int):
    return api_client.create_load_sheet(
        F.load_sheet_payload(world.plan_id, plan_version),
        load_controller_headers(LOAD_CONTROLLER_1),
    )


class TestSheetIssuanceDependsOnDeclaration:
    def test_a_submitted_declaration_bars_issuance_even_when_it_carries_no_payload(self):
        """The booked consignment weighs nothing in the plan yet still withholds the sheet.

        PRD: "A load sheet may not be issued while any consignment on the flight
        with `is_dangerous_goods` true and `status` `BOOKED`, `ACCEPTED` or
        `LOADED` lacks a declaration in `ACCEPTED` status; the refusal is
        `ERR_DG_NOT_ACCEPTED`."

        Design: Difficulty/cross_entity_state_dependency/sheet_issuance_requires_accepted_hazmat
        """
        world = _undeclared_dg_world()
        A.assert_plan_figures(
            world.plan,
            base_payload_kg=6100.00,
            index_zfw=78.66,
            zero_fuel_weight_kg=48650.00,
            mac_zfw_pct=14.03,
            takeoff_weight_kg=58200.00,
            index_tow=87.26,
            mac_tow_pct=15.24,
            underload_kg=14080.00,
        )
        A.assert_flight_state(
            fx.refresh_flight(world), load_release_state="HELD_FOR_DG", dg_hold_count=1
        )

        response = _issue(world, int(world.plan["version"]))

        validate_error(response, E.DG_NOT_ACCEPTED, 409)

    def test_accepting_the_declaration_clears_the_hold_without_accepting_the_cargo(self):
        """Declaration acceptance resolves the hold ledger and nothing else.

        PRD: "In both directions, when the resolution takes `dg_hold_count` to 0 —
        that is, when the last outstanding declaration on the flight has been
        resolved either way — the flight's `load_release_state` returns from
        `HELD_FOR_DG` to `OPEN` and `dg_hold_count` reads 0."

        Design: Difficulty/cross_entity_state_dependency/sheet_issuance_requires_accepted_hazmat
        """
        world = _undeclared_dg_world()
        validate_error(_issue(world, int(world.plan["version"])), E.DG_NOT_ACCEPTED, 409)

        fx.accept_declaration(
            world.declaration_id(_UNDECLARED_DG), dg_officer_headers(DG_OFFICER_1)
        )

        A.assert_declaration_state(
            fx.refresh_declaration(world, _UNDECLARED_DG),
            status="ACCEPTED",
            accepted_by_user_id=DG_OFFICER_1,
            notoc_issued=False,
        )
        A.assert_flight_state(
            fx.refresh_flight(world), load_release_state="OPEN", dg_hold_count=0
        )
        A.assert_cargo_state(fx.refresh_cargo(world, _UNDECLARED_DG), status="BOOKED")

    def test_the_same_plan_version_then_issues_the_sheet(self):
        """The refused issuance did not move the plan, so the held version still fits.

        PRD: "`notoc_reference` is populated with the notification-to-captain
        reference when — and only when — the flight carries at least one
        declaration in `ACCEPTED` status; a flight with no dangerous goods leaves
        it absent."

        Design: Difficulty/cross_entity_state_dependency/sheet_issuance_requires_accepted_hazmat
        """
        world = _undeclared_dg_world()
        held_version = int(world.plan["version"])
        validate_error(_issue(world, held_version), E.DG_NOT_ACCEPTED, 409)
        fx.accept_declaration(
            world.declaration_id(_UNDECLARED_DG), dg_officer_headers(DG_OFFICER_1)
        )

        sheet = get_success_data(_issue(world, held_version), 201)

        A.assert_sheet_figures(
            sheet,
            status="ISSUED",
            sheet_no=1,
            issued_by_user_id=LOAD_CONTROLLER_1,
            issued_takeoff_weight_kg=58200.00,
            issued_index_tow=87.26,
            issued_payload_kg=6100.00,
            lmc_allowance_kg=500.00,
            weight_program_documentation_ref="OM-A 8.1.3 rev 12",
        )
        assert sheet["notoc_reference"], (
            "a flight carrying accepted dangerous goods should publish a notoc reference"
        )
        A.assert_plan_figures(
            fx.refresh_plan(world), status="SHEET_ISSUED", base_payload_kg=6100.00
        )


# ---------------------------------------------------------------------------
# A flight depends on the posture of its airframe
# ---------------------------------------------------------------------------


def _grounded_airframe_world():
    """Two airframes, one of them grounded after it already had a flight planned."""
    base = fx.reference_world(compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]])
    sibling = fx.sibling_airframe_world(base, compartment_specs=[])
    fx.flight_world(base, flight_number="LX1700")
    validate_success(api_client.ground_aircraft(base.aircraft_id, ADMIN), 200)
    return base, sibling


def _next_day_flight(world: fx.Scenario, aircraft_id: str, flight_number: str):
    return api_client.create_flight(
        F.flight_payload(
            aircraft_id,
            world.runway_id,
            world.program_id,
            flight_number=flight_number,
            scheduled_off_block_utc="2026-08-16T10:00:00Z",
            scheduled_on_block_utc="2026-08-16T12:30:00Z",
        ),
        LOAD_CONTROLLER,
    )


class TestFlightCreationDependsOnAirframe:
    def test_a_grounded_airframe_cannot_take_a_new_flight(self):
        """The airframe's posture is checked when the flight is opened.

        PRD: "Reference-data posture at flight creation — `ERR_AIRCRAFT_GROUNDED`,
        `ERR_RUNWAY_CLOSED` or `ERR_WEIGHT_PROGRAM_WITHDRAWN`, 409."

        Design: Difficulty/cross_entity_state_dependency/flight_creation_blocked_by_grounded_aircraft
        """
        base, _ = _grounded_airframe_world()

        response = _next_day_flight(base, base.aircraft_id, "LX1702")

        validate_error(response, E.AIRCRAFT_GROUNDED, 409)
        grounded = get_success_data(api_client.get_aircraft(base.aircraft_id, ADMIN))
        assert grounded["status"] == "GROUNDED", "the grounded airframe should read GROUNDED"

    def test_a_serviceable_sibling_takes_the_flight_with_its_derived_limits(self):
        """The second airframe is untouched and its flight derives the usual figures.

        PRD: "`dry_operating_weight_kg` is the airframe's `basic_empty_weight_kg`
        plus the flight's `crew_weight_kg`."

        Design: Difficulty/cross_entity_state_dependency/flight_creation_blocked_by_grounded_aircraft
        """
        base, sibling = _grounded_airframe_world()
        validate_error(
            _next_day_flight(base, base.aircraft_id, "LX1702"), E.AIRCRAFT_GROUNDED, 409
        )

        admitted = get_success_data(
            _next_day_flight(base, sibling.aircraft_id, "LX1704"), 201
        )

        A.assert_flight_capacity(
            admitted,
            dry_operating_weight_kg=42550.00,
            dry_operating_index=62.53,
            performance_limited_takeoff_weight_kg=73810.00,
            allowed_payload_kg=20180.00,
            limiting_factor="MZFW",
        )
        serviceable = get_success_data(api_client.get_aircraft(sibling.aircraft_id, ADMIN))
        assert serviceable["status"] == "IN_SERVICE", "the sibling airframe stays in service"

    def test_grounding_does_not_disturb_the_flight_already_planned(self):
        """The check gates creation only; the airframe's existing flight runs on.

        PRD: "The flight is created with `status` `PLANNING`, `load_release_state`
        `OPEN` and `dg_hold_count` 0."

        Design: Difficulty/cross_entity_state_dependency/flight_creation_blocked_by_grounded_aircraft
        """
        base, _ = _grounded_airframe_world()
        validate_error(
            _next_day_flight(base, base.aircraft_id, "LX1702"), E.AIRCRAFT_GROUNDED, 409
        )

        existing = fx.refresh_flight(base)

        A.assert_flight_state(existing, status="PLANNING")
        A.assert_flight_capacity(existing, allowed_payload_kg=20180.00)
        rows, meta = validate_paginated(
            api_client.list_flights(LOAD_CONTROLLER, {"aircraft_id": base.aircraft_id})
        )
        A.assert_pagination_meta(meta, total_count=1)


# ---------------------------------------------------------------------------
# A final-basis audit depends on the commander's signature
# ---------------------------------------------------------------------------

_AUDIT_CARGO = "724-12350001"
_ACTUALS = (4650, 1450, 400)


def _issued_but_unsigned_world() -> fx.Scenario:
    """A sheet issued and left waiting on the flight deck."""
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H1", "H4"), band_specs=[F.CANONICAL_BANDS[1]]
    )
    fx.plan_world(world, flight_overrides={"flight_number": "LX1710"})
    fx.seat(world, "OC", male_count=50, child_count=6, infant_count=4)
    fx.stow_bags(world, "H1", 112, 1450)
    fx.book_and_stow_cargo(
        world, _AUDIT_CARGO, "H4", item_kind="GENERAL", weight_kg=400, length_m=0.8
    )
    fx.compute_plan(world)
    fx.issue_sheet(world, load_controller_headers(LOAD_CONTROLLER_1))
    return world


def _open_audit(world: fx.Scenario, basis: str):
    return api_client.create_load_audit(
        F.load_audit_payload(world.flight_id, basis, *_ACTUALS), AUDIT_INSPECTOR
    )


class TestFinalBasisAuditDependsOnSheet:
    def test_a_final_basis_audit_is_refused_while_no_sheet_is_signed(self):
        """An issued but unaccepted sheet is not a final record to audit against.

        PRD: "A `FINAL_BASIS` audit therefore needs a sheet in `ACCEPTED` or
        `AMENDED` status on that highest-revision plan, and is refused with
        `ERR_NO_ACCEPTED_SHEET` when none exists; `DOCUMENTED_BASIS` may be
        requested from any of the three permitted flight states without such a
        sheet."

        Design: Difficulty/cross_entity_state_dependency/audit_final_basis_requires_accepted_sheet
        """
        world = _issued_but_unsigned_world()
        A.assert_flight_state(fx.refresh_flight(world), status="LOAD_CONTROLLED")
        A.assert_sheet_figures(world.sheet, status="ISSUED")
        A.assert_cargo_state(fx.refresh_cargo(world, _AUDIT_CARGO), status="ACCEPTED")

        response = _open_audit(world, "FINAL_BASIS")

        validate_error(response, E.NO_ACCEPTED_SHEET, 409)

    def test_a_documented_basis_audit_needs_no_sheet_and_counts_only_loaded_cargo(self):
        """The plan-based audit opens at once, and the unstowed cargo reads as missing.

        PRD: "The documented passenger figure is the sum of `line_weight_kg` over
        that plan's passenger lines; the documented bag figure is the sum of
        `effective_weight_kg` over its bag allocations; the documented cargo figure
        is the sum of `weight_kg` over the flight's consignments in `LOADED`
        status."

        Design: Difficulty/cross_entity_state_dependency/audit_final_basis_requires_accepted_sheet
        """
        world = _issued_but_unsigned_world()
        validate_error(_open_audit(world, "FINAL_BASIS"), E.NO_ACCEPTED_SHEET, 409)

        audit = get_success_data(_open_audit(world, "DOCUMENTED_BASIS"), 201)

        A.assert_audit_figures(
            audit,
            basis="DOCUMENTED_BASIS",
            pax_delta_kg=0.00,
            bag_delta_kg=0.00,
            cargo_delta_kg=400.00,
            total_absolute_discrepancy_kg=400.00,
            severity="MINOR",
            status="OPEN",
        )

    def test_the_signature_unlocks_the_final_basis_and_leaves_the_earlier_audit_alone(self):
        """Acceptance loads the cargo, so the same actuals now read a clean audit.

        PRD: "`severity` follows from that total against two thresholds, half a
        tonne and one tonne, with both band boundaries inclusive at their upper
        end: `NONE` when the total is exactly 0, `MINOR` when it is strictly above
        0 and at most 500 kilograms, `MAJOR` when it is strictly above 500
        kilograms and at most 1000 kilograms, and `CRITICAL` when it is strictly
        above 1000 kilograms."

        Design: Difficulty/cross_entity_state_dependency/audit_final_basis_requires_accepted_sheet
        """
        world = _issued_but_unsigned_world()
        validate_error(_open_audit(world, "FINAL_BASIS"), E.NO_ACCEPTED_SHEET, 409)
        documented = get_success_data(_open_audit(world, "DOCUMENTED_BASIS"), 201)

        fx.accept_sheet(world, captain_headers(CAPTAIN_1))

        A.assert_flight_state(fx.refresh_flight(world), load_release_state="RELEASED")
        A.assert_cargo_state(fx.refresh_cargo(world, _AUDIT_CARGO), status="LOADED")
        final = get_success_data(_open_audit(world, "FINAL_BASIS"), 201)
        A.assert_audit_figures(
            final,
            basis="FINAL_BASIS",
            pax_delta_kg=0.00,
            bag_delta_kg=0.00,
            cargo_delta_kg=0.00,
            total_absolute_discrepancy_kg=0.00,
            severity="NONE",
        )
        stale = get_success_data(
            api_client.get_load_audit(str(documented["id"]), audit_inspector_headers())
        )
        A.assert_audit_figures(
            stale, total_absolute_discrepancy_kg=400.00, severity="MINOR"
        )
        rows, meta = validate_paginated(
            api_client.list_flight_load_audits(world.flight_id, AUDIT_INSPECTOR)
        )
        A.assert_pagination_meta(meta, total_count=2)
