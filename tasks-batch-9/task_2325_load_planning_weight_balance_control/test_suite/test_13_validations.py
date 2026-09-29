"""Refusals: the ladder's order, its referential rungs and its business ceilings."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ADMIN,
    AUDIT_INSPECTOR,
    AUDIT_INSPECTOR_1,
    DG_OFFICER_1,
    DG_OFFICER_2,
    LOAD_CONTROLLER,
    RAMP_AGENT,
    api_client,
)
from test_helpers import ApiErrorId as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import dg_officer_headers

_SPECS = {spec["code"]: spec for spec in F.CANONICAL_COMPARTMENTS}


def _layout(*codes: str):
    return [_SPECS[code] for code in codes]


def _unknown(tag: str) -> str:
    """An identifier of the right shape that no row will ever carry."""
    return f"00000000-0000-0000-0000-0000000000{tag}"


# ---------------------------------------------------------------------------
# Referential rungs: body foreign keys and uniqueness
# ---------------------------------------------------------------------------

_CG_FK = "724-13000001"


class TestBodyForeignKeys:
    def test_thirteen_broken_body_references_each_name_their_own_entity(self):
        """Every creation surface reports the entity its body failed to resolve.

        PRD: "Body foreign-key existence — every foreign key in the request body
        resolves; otherwise the matching not-found error, 404."

        Design: Corner/validations/body_foreign_key_not_found_reports_the_referenced_entity
        """
        world = fx.reference_world(
            compartment_specs=_layout("OC"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.plan_world(world, flight_overrides={"flight_number": "LX1602"})
        fx.book_cargo(world, _CG_FK, item_kind="GENERAL", weight_kg=400, length_m=1.2)
        oc = world.compartment_id("OC")

        attempts = [
            (
                api_client.create_performance_band(
                    F.performance_band_payload(_unknown("d1"), 15, 30, 74500), ADMIN
                ),
                E.RUNWAY_NOT_FOUND,
            ),
            (
                api_client.create_flight(
                    F.flight_payload(
                        _unknown("d2"),
                        world.runway_id,
                        world.program_id,
                        flight_number="LX1660",
                    ),
                    LOAD_CONTROLLER,
                ),
                E.AIRCRAFT_NOT_FOUND,
            ),
            (
                api_client.create_flight(
                    F.flight_payload(
                        world.aircraft_id,
                        _unknown("d3"),
                        world.program_id,
                        flight_number="LX1662",
                    ),
                    LOAD_CONTROLLER,
                ),
                E.RUNWAY_NOT_FOUND,
            ),
            (
                api_client.create_flight(
                    F.flight_payload(
                        world.aircraft_id,
                        world.runway_id,
                        _unknown("d4"),
                        flight_number="LX1664",
                    ),
                    LOAD_CONTROLLER,
                ),
                E.WEIGHT_PROGRAM_NOT_FOUND,
            ),
            (
                api_client.create_load_plan(
                    F.load_plan_payload(_unknown("d5"), 1), LOAD_CONTROLLER
                ),
                E.FLIGHT_NOT_FOUND,
            ),
            (
                api_client.create_pax_line(
                    F.pax_line_payload(_unknown("d6"), oc, male_count=1), LOAD_CONTROLLER
                ),
                E.LOAD_PLAN_NOT_FOUND,
            ),
            (
                api_client.create_pax_line(
                    F.pax_line_payload(world.plan_id, _unknown("d7"), male_count=1),
                    LOAD_CONTROLLER,
                ),
                E.COMPARTMENT_NOT_FOUND,
            ),
            (
                api_client.create_cargo_item(
                    F.cargo_item_payload(
                        _unknown("d8"), "724-13000009", weight_kg=400, length_m=1.2
                    ),
                    RAMP_AGENT,
                ),
                E.FLIGHT_NOT_FOUND,
            ),
            (
                api_client.assign_cargo_item(
                    world.cargo_id(_CG_FK),
                    {"assigned_compartment_id": _unknown("d9")},
                    RAMP_AGENT,
                ),
                E.COMPARTMENT_NOT_FOUND,
            ),
            (
                api_client.create_hazmat_declaration(
                    F.hazmat_declaration_payload(_unknown("e1"), 100), RAMP_AGENT
                ),
                E.CARGO_ITEM_NOT_FOUND,
            ),
            (
                api_client.create_load_sheet(
                    F.load_sheet_payload(_unknown("e2"), 1), LOAD_CONTROLLER
                ),
                E.LOAD_PLAN_NOT_FOUND,
            ),
            (
                api_client.create_last_minute_change(
                    F.last_minute_change_payload(
                        _unknown("e3"), "PAX_ADD", oc, male_count=1
                    ),
                    LOAD_CONTROLLER,
                ),
                E.LOAD_SHEET_NOT_FOUND,
            ),
            (
                api_client.create_load_audit(
                    F.load_audit_payload(_unknown("e4"), "DOCUMENTED_BASIS", 0, 0, 0),
                    AUDIT_INSPECTOR,
                ),
                E.FLIGHT_NOT_FOUND,
            ),
        ]

        for response, expected_error in attempts:
            validate_error(response, expected_error, 404)
        A.assert_cargo_state(
            fx.refresh_cargo(world, _CG_FK), assigned_compartment_id=None
        )
        A.assert_plan_figures(fx.refresh_plan(world), status="DRAFT")


_CG_DUP = "724-14000001"


class TestUniquenessConstraints:
    def test_all_seven_declared_keys_refuse_their_second_write(self):
        """Each uniqueness scope is enforced on its own creation surface.

        PRD: "Uniqueness — `Aircraft.registration` unique across airframes; `code`
        unique per `aircraft_id` on compartments; `designator` unique per
        `airport_code` on runways; `WeightProgram.code` unique across programmes;
        `awb_number` unique per `flight_id` on consignments; at most one
        `PaxDistributionLine` per plan-and-compartment pair; at most one
        `BagAllocation` per plan-and-compartment pair."

        Design: Corner/validations/duplicate_key_rejected_on_every_declared_uniqueness_constraint
        """
        world = fx.reference_world(
            compartment_specs=_layout("OC", "H1"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.plan_world(world, flight_overrides={"flight_number": "LX1602"})
        fx.book_cargo(world, _CG_DUP, item_kind="GENERAL", weight_kg=400, length_m=1.2)
        fx.seat(world, "OC", male_count=25, female_count=35)
        fx.stow_bags(world, "H1", 112, 1450)

        repeats = [
            api_client.create_aircraft(F.aircraft_payload("HB-AAA"), ADMIN),
            api_client.create_compartment(
                F.compartment_payload(
                    world.aircraft_id, "OC", "CABIN_ZONE", 20.0, 7000, 1800, 7.0,
                    seat_capacity=50,
                ),
                ADMIN,
            ),
            api_client.create_runway(F.runway_payload(), ADMIN),
            api_client.create_weight_program(F.weight_program_payload(), ADMIN),
            api_client.create_cargo_item(
                F.cargo_item_payload(
                    world.flight_id, _CG_DUP, item_kind="MAIL", weight_kg=120, length_m=0.8
                ),
                RAMP_AGENT,
            ),
            api_client.create_pax_line(
                F.pax_line_payload(
                    world.plan_id, world.compartment_id("OC"), male_count=1
                ),
                LOAD_CONTROLLER,
            ),
            api_client.create_bag_allocation(
                F.bag_allocation_payload(
                    world.plan_id, world.compartment_id("H1"), 10, 130
                ),
                LOAD_CONTROLLER,
            ),
        ]

        for response in repeats:
            validate_error(response, E.DUPLICATE_KEY, 409)
        aircraft = get_success_data(
            api_client.get_aircraft(world.aircraft_id, ADMIN), 200
        )
        assert aircraft["type_code"] == "B738", "the original airframe should be untouched"
        compartment = get_success_data(
            api_client.get_compartment(world.compartment_id("OC"), ADMIN), 200
        )
        assert float(compartment["arm_m"]) == 22.900, (
            "the original cabin zone should keep its own arm"
        )
        runway = get_success_data(api_client.get_runway(world.runway_id, ADMIN), 200)
        assert float(runway["length_m"]) == 3900, "the original runway should be untouched"
        program = get_success_data(
            api_client.get_weight_program(world.program_id, ADMIN), 200
        )
        assert program["program_kind"] == "STANDARD", "the original programme should stand"
        A.assert_cargo_state(fx.refresh_cargo(world, _CG_DUP), item_kind="GENERAL")
        line = get_success_data(
            api_client.get_pax_line(world.pax_line_id("OC"), LOAD_CONTROLLER), 200
        )
        assert line["male_count"] == 25, "the original passenger line should be untouched"
        allocation = get_success_data(
            api_client.get_bag_allocation(
                world.bag_allocation_id("H1"), LOAD_CONTROLLER
            ),
            200,
        )
        A.assert_kg(allocation["bag_weight_kg"], 1450.00, "bag_weight_kg")
        rows, meta = validate_paginated(
            api_client.list_pax_lines(LOAD_CONTROLLER, {"load_plan_id": world.plan_id})
        )
        A.assert_pagination_meta(meta, total_count=1)
        rows, meta = validate_paginated(
            api_client.list_bag_allocations(
                LOAD_CONTROLLER, {"load_plan_id": world.plan_id}
            )
        )
        A.assert_pagination_meta(meta, total_count=1)


# ---------------------------------------------------------------------------
# Reference-data posture and the state ladder
# ---------------------------------------------------------------------------


class TestClosedRunway:
    def test_closing_a_runway_bars_new_flights_and_spares_the_old_one(self):
        """The posture gate bites only at creation, never retroactively.

        PRD: "Referencing a grounded airframe yields `ERR_AIRCRAFT_GROUNDED`, a
        closed runway yields `ERR_RUNWAY_CLOSED`, and a withdrawn programme yields
        `ERR_WEIGHT_PROGRAM_WITHDRAWN`, each with HTTP 409."

        Design: Corner/validations/closed_runway_blocks_flight_creation
        """
        world = fx.reference_world(
            compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.flight_world(world, flight_number="LX1602")

        closed = get_success_data(
            api_client.close_runway(world.runway_id, ADMIN), 200
        )
        response = api_client.create_flight(
            F.flight_payload(
                world.aircraft_id,
                world.runway_id,
                world.program_id,
                flight_number="LX1670",
                scheduled_off_block_utc="2026-08-15T13:20:00Z",
                scheduled_on_block_utc="2026-08-15T15:00:00Z",
            ),
            LOAD_CONTROLLER,
        )

        validate_error(response, E.RUNWAY_CLOSED, 409)
        assert closed["status"] == "CLOSED", "closing should move the runway to CLOSED"
        rows, meta = validate_paginated(
            api_client.list_flights(
                LOAD_CONTROLLER, {"departure_runway_id": world.runway_id}
            )
        )
        A.assert_pagination_meta(meta, total_count=1)
        A.assert_flight_state(fx.refresh_flight(world), status="PLANNING")


_GATE_BAG_DRAFT = "724-15000001"


class TestDraftPlanStateLadder:
    def test_a_draft_plan_refuses_offload_gate_bags_and_issuance_alike(self):
        """All three post-computation operations demand a computed plan.

        PRD: "Load-plan state — `ERR_PLAN_INVALID_STATE`, 409, on computing a plan,
        applying an offload, presenting a gate bag, issuing a sheet, creating a
        passenger line, creating a bag allocation, and deleting a passenger line."

        Design: Corner/validations/plan_state_ladder_rejects_offload_gate_bags_and_issuance_on_a_draft_plan
        """
        world = fx.fx_a(flight_overrides={"flight_number": "LX1602"})
        A.assert_plan_figures(world.plan, status="DRAFT")

        refusals = [
            api_client.apply_offload(world.plan_id, LOAD_CONTROLLER),
            api_client.add_gate_bag(
                world.plan_id,
                F.gate_bag_payload(
                    _GATE_BAG_DRAFT, 20, world.compartment_id("H1"), length_m=0.6
                ),
                RAMP_AGENT,
            ),
            api_client.create_load_sheet(
                F.load_sheet_payload(world.plan_id, int(world.plan["version"])),
                LOAD_CONTROLLER,
            ),
        ]

        for response in refusals:
            validate_error(response, E.PLAN_INVALID_STATE, 409)
        A.assert_plan_figures(
            fx.refresh_plan(world), status="DRAFT", deferred_bag_weight_kg=0.00
        )
        A.assert_flight_state(fx.refresh_flight(world), status="PLANNING")
        rows, meta = validate_paginated(
            api_client.list_load_plan_load_sheets(world.plan_id, LOAD_CONTROLLER)
        )
        A.assert_pagination_meta(meta, total_count=0)
        rows, meta = validate_paginated(
            api_client.list_cargo_items(RAMP_AGENT, {"flight_id": world.flight_id})
        )
        A.assert_pagination_meta(meta, total_count=0)


# ---------------------------------------------------------------------------
# Consignment and declaration state
# ---------------------------------------------------------------------------

_CG_AUTO = "724-16000001"
_CG_BOOKED = "724-16000002"


class TestConsignmentState:
    def test_an_auto_accepted_consignment_cannot_be_accepted_again(self):
        """Both ends of the state rule refuse: a second accept and a second refusal.

        PRD: "Explicit acceptance requires the consignment to be `BOOKED` and the
        flight to be `PLANNING` or `LOAD_CONTROLLED`, and for a dangerous-goods
        consignment it additionally requires a declaration on that consignment
        already sitting in `ACCEPTED` status; a `BOOKED` consignment may instead be
        refused, which moves it to `REJECTED` and clears its
        `assigned_compartment_id`."

        Design: Corner/validations/acceptance_of_an_already_accepted_consignment_rejected
        """
        world = fx.reference_world(
            compartment_specs=_layout("H4"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.flight_world(world, flight_number="LX1602")
        fx.book_cargo(world, _CG_AUTO, item_kind="GENERAL", weight_kg=400, length_m=1.2)
        fx.book_cargo(world, _CG_BOOKED, item_kind="GATE_BAG", weight_kg=20, length_m=0.6)

        validate_error(
            api_client.accept_cargo_item(world.cargo_id(_CG_AUTO), RAMP_AGENT),
            E.CARGO_INVALID_STATE,
            409,
        )
        refused = get_success_data(
            api_client.reject_cargo_item(world.cargo_id(_CG_BOOKED), RAMP_AGENT), 200
        )
        validate_error(
            api_client.reject_cargo_item(world.cargo_id(_CG_BOOKED), RAMP_AGENT),
            E.CARGO_INVALID_STATE,
            409,
        )

        A.assert_cargo_state(refused, status="REJECTED", assigned_compartment_id=None)
        A.assert_cargo_state(fx.refresh_cargo(world, _CG_AUTO), status="ACCEPTED")
        A.assert_cargo_state(fx.refresh_cargo(world, _CG_BOOKED), status="REJECTED")


_DG_RESOLVED = "724-17000001"


class TestDeclarationState:
    def test_a_decided_declaration_refuses_both_a_second_yes_and_a_first_no(self):
        """One decision only, and the hold is not decremented twice.

        PRD: "A `DangerousGoodsOfficer` resolves each declaration, and only from
        `SUBMITTED`: acceptance or rejection of a declaration in any other status is
        `ERR_DECLARATION_INVALID_STATE`."

        Design: Corner/validations/second_decision_on_a_resolved_declaration_rejected
        """
        world = fx.reference_world(
            compartment_specs=_layout("H4"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.flight_world(world, flight_number="LX1602")
        fx.book_and_stow_cargo(
            world, _DG_RESOLVED, "H4", item_kind="GENERAL", weight_kg=400,
            length_m=1.2, is_dangerous_goods=True,
        )
        fx.submit_declaration(world, _DG_RESOLVED, 400)
        declaration_id = world.declaration_id(_DG_RESOLVED)
        fx.accept_declaration(declaration_id, dg_officer_headers(DG_OFFICER_1))
        second_officer = dg_officer_headers(DG_OFFICER_2)

        validate_error(
            api_client.accept_hazmat_declaration(declaration_id, second_officer),
            E.DECLARATION_INVALID_STATE,
            409,
        )
        validate_error(
            api_client.reject_hazmat_declaration(declaration_id, second_officer),
            E.DECLARATION_INVALID_STATE,
            409,
        )

        A.assert_declaration_state(
            fx.refresh_declaration(world, _DG_RESOLVED),
            status="ACCEPTED",
            accepted_by_user_id=DG_OFFICER_1,
        )
        A.assert_flight_state(
            fx.refresh_flight(world), dg_hold_count=0, load_release_state="OPEN"
        )
        A.assert_cargo_state(fx.refresh_cargo(world, _DG_RESOLVED), status="BOOKED")


# ---------------------------------------------------------------------------
# Audit state and its data-dependent guard
# ---------------------------------------------------------------------------


class TestAuditInvestigationGuard:
    def test_only_the_major_audit_may_open_an_investigation(self):
        """Two OPEN audits, one centikilogram apart, take different routes.

        PRD: "An audit whose `severity` is `MAJOR` or `CRITICAL` may be moved from
        `OPEN` to `INVESTIGATING`, and only from there to `CLOSED`; attempting to
        open an investigation on an audit whose `severity` is `NONE` or `MINOR` is
        refused with `ERR_AUDIT_INVALID_STATE`, as is attempting it on an audit that
        is not `OPEN`."

        Design: Corner/validations/investigation_is_available_only_above_the_minor_severity
        """
        world = fx.fx_a_computed(flight_overrides={"flight_number": "LX1602"})
        minor = get_success_data(
            api_client.create_load_audit(
                F.load_audit_payload(
                    world.flight_id, "DOCUMENTED_BASIS", 5150, 1450, 0
                ),
                AUDIT_INSPECTOR,
            ),
            201,
        )
        major = get_success_data(
            api_client.create_load_audit(
                F.load_audit_payload(
                    world.flight_id, "DOCUMENTED_BASIS", 5150.01, 1450, 0
                ),
                AUDIT_INSPECTOR,
            ),
            201,
        )

        validate_error(
            api_client.investigate_load_audit(str(minor["id"]), AUDIT_INSPECTOR),
            E.AUDIT_INVALID_STATE,
            409,
        )
        opened = get_success_data(
            api_client.investigate_load_audit(str(major["id"]), AUDIT_INSPECTOR), 200
        )

        still_open = get_success_data(
            api_client.get_load_audit(str(minor["id"]), AUDIT_INSPECTOR), 200
        )
        A.assert_audit_figures(still_open, status="OPEN", severity="MINOR")
        A.assert_audit_figures(opened, status="INVESTIGATING", severity="MAJOR")


class TestAuditClosureNote:
    def test_a_whitespace_note_does_not_close_an_audit_but_a_real_one_does(self):
        """The note must carry content, and closure records who wrote it.

        PRD: "Either way, closure requires a non-empty `finding_note` recording the
        investigator's narrative — an empty or absent note is
        `ERR_FINDING_NOTE_REQUIRED` — and closure sets `closed_by_user_id` to the
        acting `X-User-ID` and increments the audit's `version` by 1."

        Design: Corner/validations/closing_an_audit_without_a_finding_note_rejected
        """
        world = fx.fx_a_computed(flight_overrides={"flight_number": "LX1602"})
        audit = get_success_data(
            api_client.create_load_audit(
                F.load_audit_payload(world.flight_id, "DOCUMENTED_BASIS", 4650, 1450, 0),
                AUDIT_INSPECTOR,
            ),
            201,
        )
        A.assert_audit_figures(
            audit, total_absolute_discrepancy_kg=0.00, severity="NONE", status="OPEN"
        )
        note = "Documented figures match the ramp tally."

        validate_error(
            api_client.close_load_audit(
                str(audit["id"]), F.close_audit_payload("   "), AUDIT_INSPECTOR
            ),
            E.FINDING_NOTE_REQUIRED,
            422,
        )
        still_open = get_success_data(
            api_client.get_load_audit(str(audit["id"]), AUDIT_INSPECTOR), 200
        )
        closed = get_success_data(
            api_client.close_load_audit(
                str(audit["id"]), F.close_audit_payload(note), AUDIT_INSPECTOR
            ),
            200,
        )

        A.assert_audit_figures(still_open, status="OPEN", closed_by_user_id=None)
        A.assert_audit_figures(
            closed,
            status="CLOSED",
            closed_by_user_id=AUDIT_INSPECTOR_1,
            finding_note=note,
        )


# ---------------------------------------------------------------------------
# Ladder ordering between two simultaneously violated rules
# ---------------------------------------------------------------------------


class TestAuthorisationBeforeExistence:
    def test_the_role_boundary_does_not_leak_which_rows_exist(self):
        """The forbidden caller and the permitted caller hear different answers.

        PRD: "Authorisation — the acting role appears in the called endpoint's
        authorised role list; otherwise `ERR_UNAUTHORIZED`, 403."

        Design: Corner/validations/role_check_beats_existence_check_returns_unauthorized
        """
        aircraft = fx.create_aircraft("HB-AAA")

        validate_error(
            api_client.ground_aircraft(_unknown("f1"), LOAD_CONTROLLER),
            E.UNAUTHORIZED,
            403,
        )
        validate_error(
            api_client.ground_aircraft(_unknown("f1"), ADMIN),
            E.AIRCRAFT_NOT_FOUND,
            404,
        )

        stored = get_success_data(
            api_client.get_aircraft(str(aircraft["id"]), ADMIN), 200
        )
        assert stored["status"] == "IN_SERVICE", (
            f"the registered airframe should be untouched but read {stored['status']}"
        )


class TestShapeBeforeForeignKey:
    def test_a_malformed_body_hides_its_broken_reference_until_repaired(self):
        """Fixing only the count exposes the 404 that was waiting behind it.

        PRD: "Request shape — every required input field present, every enum value a
        declared member, every weight, length and count field at least 0, with
        consignment `weight_kg` and compartment `length_m` required to be strictly
        greater than 0, and `limit` within 1 through 100 with `offset` at least 0 on
        list endpoints; otherwise `ERR_INVALID_REQUEST`, 400."

        Design: Corner/validations/invalid_request_beats_foreign_key_not_found
        """
        world = fx.reference_world(
            compartment_specs=_layout("OC"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        oc = world.compartment_id("OC")

        validate_error(
            api_client.create_pax_line(
                F.pax_line_payload(_unknown("f2"), oc, male_count=-1), LOAD_CONTROLLER
            ),
            E.INVALID_REQUEST,
            400,
        )
        validate_error(
            api_client.create_pax_line(
                F.pax_line_payload(_unknown("f2"), oc, male_count=1), LOAD_CONTROLLER
            ),
            E.LOAD_PLAN_NOT_FOUND,
            404,
        )


# ---------------------------------------------------------------------------
# Well-formedness of the departure conditions
# ---------------------------------------------------------------------------


class TestPerformanceBandCoverage:
    def test_a_temperature_off_the_table_is_refused_rather_than_extrapolated(self):
        """The same body at 22 °C succeeds, so only the temperature can explain it.

        PRD: "When no band matches, the flight cannot be created and the request
        fails with `ERR_NO_PERFORMANCE_BAND`."

        Design: Corner/validations/temperature_outside_every_published_band_rejected
        """
        world = fx.reference_world(
            compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]]
        )

        validate_error(
            api_client.create_flight(
                F.flight_payload(
                    world.aircraft_id,
                    world.runway_id,
                    world.program_id,
                    flight_number="LX1680",
                    outside_air_temp_c=50,
                ),
                LOAD_CONTROLLER,
            ),
            E.NO_PERFORMANCE_BAND,
            422,
        )
        admitted = get_success_data(
            api_client.create_flight(
                F.flight_payload(
                    world.aircraft_id,
                    world.runway_id,
                    world.program_id,
                    flight_number="LX1680",
                    outside_air_temp_c=22,
                ),
                LOAD_CONTROLLER,
            ),
            201,
        )

        A.assert_flight_capacity(
            admitted, performance_limited_takeoff_weight_kg=73810.00
        )
        rows, meta = validate_paginated(api_client.list_flights(LOAD_CONTROLLER))
        A.assert_pagination_meta(meta, total_count=1)


class TestIntervalAndFuelCoherence:
    def test_a_zero_length_rotation_and_two_impossible_fuel_states_are_refused(self):
        """The fuel rule is re-run on revision, so the flight keeps its figures.

        PRD: "Fuel figures must cohere: taxi fuel must not exceed ramp fuel, and
        trip fuel must not exceed ramp fuel less taxi fuel; a violation is
        `ERR_FUEL_FIGURES_INCONSISTENT`."

        Design: Corner/validations/fuel_and_interval_consistency_rules_reject_impossible_figures
        """
        world = fx.reference_world(
            compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.flight_world(world, flight_number="LX1602")
        baseline_version = fx.flight_version(world)

        validate_error(
            api_client.create_flight(
                F.flight_payload(
                    world.aircraft_id,
                    world.runway_id,
                    world.program_id,
                    flight_number="LX1690",
                    scheduled_off_block_utc="2026-08-15T16:00:00Z",
                    scheduled_on_block_utc="2026-08-15T16:00:00Z",
                ),
                LOAD_CONTROLLER,
            ),
            E.INVALID_INTERVAL,
            422,
        )
        validate_error(
            api_client.create_flight(
                F.flight_payload(
                    world.aircraft_id,
                    world.runway_id,
                    world.program_id,
                    flight_number="LX1692",
                    scheduled_off_block_utc="2026-08-15T16:00:00Z",
                    scheduled_on_block_utc="2026-08-15T18:00:00Z",
                    ramp_fuel_kg=9800,
                    taxi_fuel_kg=9900,
                    trip_fuel_kg=100,
                ),
                LOAD_CONTROLLER,
            ),
            E.FUEL_FIGURES_INCONSISTENT,
            422,
        )
        validate_error(
            api_client.patch_flight_conditions(
                world.flight_id, {"trip_fuel_kg": 9800}, LOAD_CONTROLLER
            ),
            E.FUEL_FIGURES_INCONSISTENT,
            422,
        )

        flight = fx.refresh_flight(world)
        A.assert_kg(flight["trip_fuel_kg"], 6900.00, "trip_fuel_kg")
        A.assert_version_is(flight, baseline_version)
        rows, meta = validate_paginated(api_client.list_flights(LOAD_CONTROLLER))
        A.assert_pagination_meta(meta, total_count=1)


# ---------------------------------------------------------------------------
# Compartment ceilings and cabin capacity
# ---------------------------------------------------------------------------

_CG_HOLD = "724-18000001"


class TestHoldCeilings:
    def test_the_mass_ceiling_and_the_running_load_ceiling_fire_independently(self):
        """A wide hold overloads on mass; a short one trips only on load per metre.

        PRD: "Taken per hold, the allocation's `effective_weight_kg` plus the
        `weight_kg` of every consignment assigned to that hold in `ACCEPTED` or
        `LOADED` status must not exceed the hold's `max_weight_kg`, or the write is
        refused with `ERR_COMPARTMENT_OVERLOAD`."

        Design: Corner/validations/hold_limits_reject_aggregate_overload_and_running_load_separately
        """
        world = fx.reference_world(
            compartment_specs=[_SPECS["H4"], F.SHORT_HOLD_COMPARTMENT],
            band_specs=[F.CANONICAL_BANDS[1]],
        )
        fx.plan_world(world, flight_overrides={"flight_number": "LX1602"})
        fx.book_cargo(world, _CG_HOLD, item_kind="GENERAL", weight_kg=300, length_m=1.0)

        allocation = fx.stow_bags(world, "H4", 370, 4800)
        overload = api_client.assign_cargo_item(
            world.cargo_id(_CG_HOLD),
            {"assigned_compartment_id": world.compartment_id("H4")},
            RAMP_AGENT,
        )
        running_load = api_client.create_bag_allocation(
            F.bag_allocation_payload(
                world.plan_id, world.compartment_id("H6"), 154, 2000
            ),
            RAMP_AGENT,
        )

        A.assert_kg(allocation["effective_weight_kg"], 4800.00, "effective_weight_kg")
        validate_error(overload, E.COMPARTMENT_OVERLOAD, 422)
        A.assert_cargo_state(
            fx.refresh_cargo(world, _CG_HOLD), assigned_compartment_id=None
        )
        validate_error(running_load, E.RUNNING_LOAD_EXCEEDED, 422)
        rows, meta = validate_paginated(
            api_client.list_bag_allocations(
                LOAD_CONTROLLER, {"load_plan_id": world.plan_id}
            )
        )
        A.assert_pagination_meta(meta, total_count=1)
        rows, meta = validate_paginated(
            api_client.list_aircraft_compartments(
                world.aircraft_id, ADMIN, {"kind": "HOLD"}
            )
        )
        A.assert_pagination_meta(meta, total_count=2)


class TestSeatCapacity:
    def test_one_passenger_over_the_zone_capacity_is_refused(self):
        """The mass is trivial for the zone, so only the seat count can refuse it.

        PRD: "Seats are consumed by adults and seated children only — the sum of
        `male_count`, `female_count` and `child_count` must not exceed the
        compartment's `seat_capacity`, or the line is refused with
        `ERR_SEAT_CAPACITY_EXCEEDED` — while `infant_count` is excluded from that sum
        entirely, because a lap infant occupies no seat."

        Design: Corner/validations/seated_headcount_above_the_zone_capacity_rejected
        """
        world = fx.reference_world(
            compartment_specs=_layout("OC"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.plan_world(world, flight_overrides={"flight_number": "LX1602"})

        response = api_client.create_pax_line(
            F.pax_line_payload(
                world.plan_id,
                world.compartment_id("OC"),
                male_count=25,
                female_count=36,
            ),
            LOAD_CONTROLLER,
        )

        validate_error(response, E.SEAT_CAPACITY_EXCEEDED, 422)
        rows, meta = validate_paginated(
            api_client.list_pax_lines(LOAD_CONTROLLER, {"load_plan_id": world.plan_id})
        )
        A.assert_pagination_meta(meta, total_count=0)
        A.assert_plan_figures(fx.refresh_plan(world), status="DRAFT")

    def test_a_full_zone_still_admits_four_lap_infants(self):
        """Sixty seated plus four on laps fits, and the infants add their own mass.

        PRD: "Under `STANDARD`, the mass is the male count multiplied by the
        programme's `male_kg`, plus the female count multiplied by `female_kg`, plus
        the child count multiplied by `child_kg`, plus the infant count multiplied by
        `infant_kg` — so lap infants contribute mass even though they consume no
        seat."

        Design: Corner/validations/seated_headcount_exactly_at_capacity_with_lap_infants_passes
        """
        world = fx.reference_world(
            compartment_specs=_layout("OC"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.plan_world(world, flight_overrides={"flight_number": "LX1602"})

        response = api_client.create_pax_line(
            F.pax_line_payload(
                world.plan_id,
                world.compartment_id("OC"),
                male_count=25,
                female_count=35,
                infant_count=4,
            ),
            LOAD_CONTROLLER,
        )

        line = get_success_data(response, 201)
        A.assert_kg(line["line_weight_kg"], 4690.00, "line_weight_kg")
        A.assert_index(line["index_delta"], 27.67, "index_delta")
        assert line["infant_count"] == 4, "the four lap infants should round-trip"
        assert line["actual_weight_kg"] is None, (
            "a standard-programme line should carry no weighed figure"
        )


# ---------------------------------------------------------------------------
# Offload sufficiency
# ---------------------------------------------------------------------------

_NO_CARGO_PAX = (("OA", 42), ("OB", 60), ("OC", 60))
_NO_CARGO_BAGS = (("H1", 346, 4500), ("H4", 385, 5000), ("H5", 92, 1200))


def _restricted_without_cargo() -> fx.Scenario:
    """A plan 4776 kg over its allowed payload and carrying no consignment at all."""
    world = fx.reference_world(
        compartment_specs=_layout("OA", "OB", "OC", "H1", "H4", "H5"),
        band_specs=[F.CANONICAL_BANDS[1]],
    )
    fx.plan_world(world, flight_overrides={"flight_number": "LX1602"})
    for code, male_count in _NO_CARGO_PAX:
        fx.seat(world, code, male_count=male_count)
    for code, bag_count, bag_weight_kg in _NO_CARGO_BAGS:
        fx.stow_bags(world, code, bag_count, bag_weight_kg)
    fx.compute_plan(world)
    return world


class TestOffloadSufficiency:
    def test_passengers_and_bags_are_never_offload_candidates(self):
        """The excess is real, the candidate set is empty, and nothing is written.

        PRD: "If the walk exhausts the candidates while the running total is still
        strictly below the excess — including the degenerate case of an empty
        candidate set against a positive excess — the operation fails with
        `ERR_OFFLOAD_INSUFFICIENT` and nothing is written."

        Design: Corner/validations/offload_with_no_eligible_consignment_rejected
        """
        world = _restricted_without_cargo()
        A.assert_plan_figures(
            world.plan,
            status="RESTRICTED",
            base_payload_kg=24956.00,
            frozen_underload_kg=-4776.00,
            restriction_status="WEIGHT_RESTRICTED",
        )

        preview = get_success_data(
            api_client.get_offload_preview(world.plan_id, LOAD_CONTROLLER), 200
        )
        refusal = api_client.apply_offload(world.plan_id, LOAD_CONTROLLER)

        A.assert_offload_preview(
            preview,
            strategy="PRIORITY_FIRST",
            excess_weight_kg=4776.00,
            offloaded_total_kg=0.00,
            offloaded_piece_count=0,
            offloaded_awb_numbers=[],
        )
        validate_error(refusal, E.OFFLOAD_INSUFFICIENT, 409)
        A.assert_plan_figures(
            fx.refresh_plan(world), status="RESTRICTED", planned_payload_kg=24956.00
        )
        A.assert_flight_state(fx.refresh_flight(world), status="PLANNING")


# ---------------------------------------------------------------------------
# Dangerous goods: segregation, eligibility and declared quantity
# ---------------------------------------------------------------------------

_DG_FLAMMABLE = "724-19000001"
_DG_OXIDISER = "724-19000002"


class TestSegregationWithinOneHold:
    def test_an_oxidiser_cannot_join_an_accepted_flammable_in_the_same_hold(self):
        """The first acceptance is what makes the second one impossible.

        PRD: "Segregation is compartment-scoped and pairwise: accepting a
        declaration whose `segregation_group` is `FLAMMABLE` is refused when some
        other consignment sharing the same `assigned_compartment_id` already carries
        a declaration in `ACCEPTED` status whose `segregation_group` is `OXIDISER`,
        and symmetrically accepting an `OXIDISER` declaration is refused when a
        `FLAMMABLE` one is already accepted in that hold."

        Design: Corner/validations/dangerous_goods_segregation_conflict_within_one_hold
        """
        world = fx.reference_world(
            compartment_specs=_layout("H4"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.flight_world(world, flight_number="LX1602")
        for awb in (_DG_FLAMMABLE, _DG_OXIDISER):
            fx.book_and_stow_cargo(
                world, awb, "H4", item_kind="GENERAL", weight_kg=400, length_m=1.2,
                is_dangerous_goods=True,
            )
        fx.submit_declaration(
            world, _DG_FLAMMABLE, 400, un_number="UN1263", imo_class="CLASS_3",
            segregation_group="FLAMMABLE",
        )
        fx.submit_declaration(
            world, _DG_OXIDISER, 400, un_number="UN1748", imo_class="CLASS_5",
            segregation_group="OXIDISER",
        )
        officer = dg_officer_headers(DG_OFFICER_1)

        accepted = get_success_data(
            api_client.accept_hazmat_declaration(
                world.declaration_id(_DG_FLAMMABLE), officer
            ),
            200,
        )
        conflict = api_client.accept_hazmat_declaration(
            world.declaration_id(_DG_OXIDISER), officer
        )

        A.assert_declaration_state(accepted, status="ACCEPTED")
        validate_error(conflict, E.DG_SEGREGATION_CONFLICT, 409)
        A.assert_declaration_state(
            fx.refresh_declaration(world, _DG_OXIDISER),
            status="SUBMITTED",
            accepted_by_user_id=None,
        )
        A.assert_flight_state(
            fx.refresh_flight(world), dg_hold_count=1, load_release_state="HELD_FOR_DG"
        )


_DG_HEAVY = "724-20000001"
_PLAIN_BAG = "724-20000002"


class TestDeclarationEligibilityAndQuantity:
    def test_an_ordinary_consignment_and_an_overstated_quantity_are_both_refused(self):
        """The flag is checked before the quantity, and neither declaration survives.

        PRD: "Only a consignment whose `is_dangerous_goods` flag is true may be
        declared, and submitting against an ordinary consignment is refused with
        `ERR_NOT_DANGEROUS_GOODS`."

        Design: Corner/validations/declaration_quantity_and_non_dangerous_declarations_rejected
        """
        world = fx.reference_world(
            compartment_specs=_layout("H4"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.flight_world(world, flight_number="LX1602")
        fx.book_and_stow_cargo(
            world, _DG_HEAVY, "H4", item_kind="GENERAL", weight_kg=400, length_m=1.2,
            is_dangerous_goods=True,
        )
        fx.book_cargo(world, _PLAIN_BAG, item_kind="GATE_BAG", weight_kg=20, length_m=0.6)

        validate_error(
            api_client.create_hazmat_declaration(
                F.hazmat_declaration_payload(world.cargo_id(_PLAIN_BAG), 20), RAMP_AGENT
            ),
            E.NOT_DANGEROUS_GOODS,
            409,
        )
        validate_error(
            api_client.create_hazmat_declaration(
                F.hazmat_declaration_payload(world.cargo_id(_DG_HEAVY), 500), RAMP_AGENT
            ),
            E.DG_QUANTITY_EXCEEDS_ITEM,
            422,
        )

        for awb in (_DG_HEAVY, _PLAIN_BAG):
            rows, meta = validate_paginated(
                api_client.list_cargo_hazmat_declarations(
                    world.cargo_id(awb), RAMP_AGENT
                )
            )
            A.assert_pagination_meta(meta, total_count=0)
        A.assert_flight_state(
            fx.refresh_flight(world), dg_hold_count=0, load_release_state="OPEN"
        )


# ---------------------------------------------------------------------------
# Gate bags: two independent constraints in one operation
# ---------------------------------------------------------------------------

_GATE_BAG_FULL_HOLD = "724-21000001"


class TestGateBagStowageBeforeBudget:
    def test_an_affordable_gate_bag_is_still_refused_by_a_full_hold(self):
        """Fourteen tonnes of underload cannot buy the last 50 kilograms of hold.

        PRD: "The named compartment must be a `HOLD` on the flight's airframe, and
        the hold's structural and running-load ceilings are checked with the bag
        included, yielding `ERR_COMPARTMENT_NOT_ON_AIRCRAFT`,
        `ERR_COMPARTMENT_KIND_MISMATCH`, `ERR_COMPARTMENT_OVERLOAD` or
        `ERR_RUNNING_LOAD_EXCEEDED` as applicable."

        Design: Corner/validations/gate_bag_that_fits_the_underload_still_fails_the_hold_limit
        """
        world = fx.reference_world(
            compartment_specs=_layout("OC", "H5"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.plan_world(world, flight_overrides={"flight_number": "LX1602"})
        fx.seat(world, "OC", male_count=25, female_count=35)
        fx.stow_bags(world, "H5", 89, 1150)
        computed = fx.compute_plan(world)
        A.assert_plan_figures(
            computed,
            status="COMPUTED",
            base_payload_kg=5800.00,
            underload_kg=14380.00,
            envelope_ok=True,
        )

        response = api_client.add_gate_bag(
            world.plan_id,
            F.gate_bag_payload(
                _GATE_BAG_FULL_HOLD, 100, world.compartment_id("H5"), length_m=0.6
            ),
            RAMP_AGENT,
        )

        validate_error(response, E.COMPARTMENT_OVERLOAD, 422)
        rows, meta = validate_paginated(
            api_client.list_cargo_items(RAMP_AGENT, {"flight_id": world.flight_id})
        )
        A.assert_pagination_meta(meta, total_count=0)
        A.assert_plan_figures(
            fx.refresh_plan(world),
            status="COMPUTED",
            deferred_bag_weight_kg=0.00,
            planned_payload_kg=5800.00,
            underload_kg=14380.00,
        )
