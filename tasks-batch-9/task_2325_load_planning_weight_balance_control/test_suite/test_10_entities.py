"""Entity creation, retrieval, listing, defaults and shape rules."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import ADMIN, AUDIT_INSPECTOR, LOAD_CONTROLLER, RAMP_AGENT, api_client
from test_helpers import ApiErrorId as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx

_SPECS = {spec["code"]: spec for spec in F.CANONICAL_COMPARTMENTS}


def _layout(*codes: str):
    return [_SPECS[code] for code in codes]


class TestAircraftRegistration:
    def test_a_registered_airframe_is_in_service_at_version_one(self):
        """Registration alone makes the airframe usable, with no activation step.

        PRD: "A newly registered airframe's `status` is `IN_SERVICE`; grounding it
        moves `status` to `GROUNDED`."

        Design: Corner/entities/aircraft_creation_returns_airframe_with_in_service_status
        """
        response = api_client.create_aircraft(F.aircraft_payload("HB-AAA"), ADMIN)

        aircraft = get_success_data(response, 201)
        assert aircraft["status"] == "IN_SERVICE", (
            f"a new airframe should be IN_SERVICE but was {aircraft['status']}"
        )
        A.assert_version_is(aircraft, 1)
        assert aircraft["registration"] == "HB-AAA", "the registration should round-trip"
        assert float(aircraft["index_c"]) == 1000, "the index constant should round-trip"
        assert float(aircraft["tow_knee_weight_kg"]) == 60000, "the knee weight should round-trip"
        assert float(aircraft["tow_aft_knee_adjust_pct_mac"]) == -1.5, (
            "the knee adjustment should round-trip as a negative figure"
        )


class TestRunwayRetrieval:
    def test_a_runway_created_without_a_slot_capacity_reads_the_declared_default(self):
        """The stored row comes back verbatim, with the omitted capacity defaulted.

        PRD: "`slot_capacity_per_window` defaults to 2 and caps how many departures
        may share one departure slot window."

        Design: Corner/entities/runway_retrieval_returns_stored_runway_with_default_slot_capacity
        """
        created = fx.create_runway(slot_capacity_per_window=None)

        stored = get_success_data(
            api_client.get_runway(str(created["id"]), LOAD_CONTROLLER), 200
        )

        assert stored["airport_code"] == "LSGG", "the airport code should round-trip"
        assert stored["designator"] == "04", "the designator should round-trip"
        assert float(stored["elevation_ft"]) == 1411, "the threshold elevation should round-trip"
        assert float(stored["length_m"]) == 3900, "the runway length should round-trip"
        assert stored["slot_capacity_per_window"] == 2, (
            "an omitted slot capacity should default to 2"
        )
        assert stored["status"] == "OPEN", "a new runway should read OPEN"


def _three_rotations() -> fx.Scenario:
    """Three planning flights on one airframe, spaced clear of both temporal rules."""
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H1"), band_specs=[F.CANONICAL_BANDS[1]]
    )
    fx.flight_world(world, flight_number="LX1602")
    for number, off_block, on_block in (
        ("LX1604", "2026-08-15T13:20:00Z", "2026-08-15T15:00:00Z"),
        ("LX1606", "2026-08-15T15:50:00Z", "2026-08-15T17:30:00Z"),
    ):
        fx.create_flight(
            world.aircraft_id,
            world.runway_id,
            world.program_id,
            flight_number=number,
            scheduled_off_block_utc=off_block,
            scheduled_on_block_utc=on_block,
        )
    return world


class TestFlightsListing:
    def test_the_page_window_moves_while_the_total_count_stands(self):
        """Two pages cover three rows, and the status filter returns all of them.

        PRD: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` — the count of rows matching the filters before the page
        window is applied — and `has_more`, which is true when rows remain beyond
        the current window."

        Design: Corner/entities/flights_listing_paginates_and_filters_by_status
        """
        world = _three_rotations()

        first_page, first_meta = validate_paginated(
            api_client.list_flights(AUDIT_INSPECTOR, {"limit": 2, "offset": 0})
        )
        second_page, second_meta = validate_paginated(
            api_client.list_flights(AUDIT_INSPECTOR, {"limit": 2, "offset": 2})
        )
        filtered, filtered_meta = validate_paginated(
            api_client.list_flights(
                AUDIT_INSPECTOR, {"status": "PLANNING", "aircraft_id": world.aircraft_id}
            )
        )

        assert len(first_page) == 2, f"the first page should hold 2 rows, held {len(first_page)}"
        A.assert_pagination_meta(first_meta, total_count=3, has_more=True, limit=2, offset=0)
        assert len(second_page) == 1, (
            f"the second page should hold the last row, held {len(second_page)}"
        )
        A.assert_pagination_meta(second_meta, total_count=3, has_more=False, offset=2)
        assert len(filtered) == 3, "the status filter should return all three flights"
        A.assert_pagination_meta(filtered_meta, total_count=3, has_more=False)
        for flight in filtered:
            A.assert_flight_state(flight, status="PLANNING")

    def test_a_limit_above_the_cap_and_a_negative_offset_are_both_malformed(self):
        """The pagination bound is a shape rule, checked before any row is read.

        PRD: "A `limit` outside the range 1 through 100, or a negative `offset`, is
        a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/flights_listing_limit_above_maximum_rejected
        """
        validate_error(
            api_client.list_flights(LOAD_CONTROLLER, {"limit": 101}), E.INVALID_REQUEST, 400
        )
        validate_error(
            api_client.list_flights(LOAD_CONTROLLER, {"offset": -1}), E.INVALID_REQUEST, 400
        )


class TestNotFoundFamily:
    def test_every_single_resource_read_names_its_own_entity(self):
        """Fourteen unknown ids yield fourteen distinct, entity-specific 404s.

        PRD: "The full not-found family is `ERR_AIRCRAFT_NOT_FOUND`,
        `ERR_COMPARTMENT_NOT_FOUND`, `ERR_RUNWAY_NOT_FOUND`,
        `ERR_PERFORMANCE_BAND_NOT_FOUND`, `ERR_WEIGHT_PROGRAM_NOT_FOUND`,
        `ERR_FLIGHT_NOT_FOUND`, `ERR_LOAD_PLAN_NOT_FOUND`,
        `ERR_PAX_LINE_NOT_FOUND`, `ERR_BAG_ALLOCATION_NOT_FOUND`,
        `ERR_CARGO_ITEM_NOT_FOUND`, `ERR_DECLARATION_NOT_FOUND`,
        `ERR_LOAD_SHEET_NOT_FOUND`, `ERR_LAST_MINUTE_CHANGE_NOT_FOUND` and
        `ERR_AUDIT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/path_id_not_found_returns_the_entity_specific_404_for_every_resource
        """
        fx.position_clock()
        unknown = "00000000-0000-0000-0000-0000000000{:02d}"
        reads = [
            (api_client.get_aircraft, E.AIRCRAFT_NOT_FOUND),
            (api_client.get_compartment, E.COMPARTMENT_NOT_FOUND),
            (api_client.get_runway, E.RUNWAY_NOT_FOUND),
            (api_client.get_performance_band, E.PERFORMANCE_BAND_NOT_FOUND),
            (api_client.get_weight_program, E.WEIGHT_PROGRAM_NOT_FOUND),
            (api_client.get_flight, E.FLIGHT_NOT_FOUND),
            (api_client.get_load_plan, E.LOAD_PLAN_NOT_FOUND),
            (api_client.get_pax_line, E.PAX_LINE_NOT_FOUND),
            (api_client.get_bag_allocation, E.BAG_ALLOCATION_NOT_FOUND),
            (api_client.get_cargo_item, E.CARGO_ITEM_NOT_FOUND),
            (api_client.get_hazmat_declaration, E.DECLARATION_NOT_FOUND),
            (api_client.get_load_sheet, E.LOAD_SHEET_NOT_FOUND),
            (api_client.get_last_minute_change, E.LAST_MINUTE_CHANGE_NOT_FOUND),
            (api_client.get_load_audit, E.AUDIT_NOT_FOUND),
        ]

        for position, (read, expected_error) in enumerate(reads, start=1):
            validate_error(read(unknown.format(position), AUDIT_INSPECTOR), expected_error, 404)


class TestRequiredFields:
    def test_a_flight_without_its_crew_weight_is_a_shape_error(self):
        """Every foreign key resolves, so only the missing field can be reported.

        PRD: "Request shape — every required input field present, every enum value
        a declared member, every weight, length and count field at least 0, with
        consignment `weight_kg` and compartment `length_m` required to be strictly
        greater than 0, and `limit` within 1 through 100 with `offset` at least 0 on
        list endpoints; otherwise `ERR_INVALID_REQUEST`, 400."

        Design: Corner/entities/create_flight_missing_required_crew_weight_returns_invalid_request
        """
        world = fx.reference_world(
            compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]]
        )
        payload = F.flight_payload(world.aircraft_id, world.runway_id, world.program_id)
        payload.pop("crew_weight_kg")

        response = api_client.create_flight(payload, LOAD_CONTROLLER)

        validate_error(response, E.INVALID_REQUEST, 400)
        rows, meta = validate_paginated(api_client.list_flights(LOAD_CONTROLLER))
        A.assert_pagination_meta(meta, total_count=0)


class TestDeclaredDefaults:
    def test_a_hold_and_a_bare_plan_take_every_contract_default(self):
        """Four omitted fields resolve to the four values the contract names.

        PRD: "Three behavioural switches may be supplied and each has a contract
        default: `gate_bag_policy` is `ABSORB_INTO_UNDERLOAD` unless `DEFER_ALL` is
        requested, `offload_strategy` is `PRIORITY_FIRST` unless `FEWEST_PIECES` is
        requested, and `rounding_mode` is `PER_LINE_THEN_SUM` unless
        `SUM_THEN_ROUND` is requested."

        Design: Corner/entities/creation_defaults_seat_capacity_gate_bag_policy_strategy_and_rounding_mode
        """
        world = fx.reference_world(
            compartment_specs=_layout("OC"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.flight_world(world, flight_number="LX1602")

        hold_payload = dict(_SPECS["H1"])
        hold_payload.pop("seat_capacity")
        hold = get_success_data(
            api_client.create_compartment(
                F.compartment_payload(aircraft_id=world.aircraft_id, **hold_payload), ADMIN
            ),
            201,
        )
        plan = fx.open_plan(world.flight_id)

        assert hold["seat_capacity"] == 0, "a hold created without a seat capacity should read 0"
        assert plan["gate_bag_policy"] == "ABSORB_INTO_UNDERLOAD", (
            f"the gate bag policy should default but was {plan['gate_bag_policy']}"
        )
        assert plan["offload_strategy"] == "PRIORITY_FIRST", (
            f"the offload strategy should default but was {plan['offload_strategy']}"
        )
        assert plan["rounding_mode"] == "PER_LINE_THEN_SUM", (
            f"the rounding mode should default but was {plan['rounding_mode']}"
        )
        assert plan["revision_no"] == 1, "a flight's first plan is revision 1"
        A.assert_plan_figures(plan, status="DRAFT", base_payload_kg=0.00, envelope_ok=False)


class TestFlightCreationComputations:
    def test_one_creation_call_runs_all_three_chained_calculations(self):
        """The dry, performance and payload families are all derived on creation.

        PRD: "`dry_operating_weight_kg` is the airframe's `basic_empty_weight_kg`
        plus the flight's `crew_weight_kg`."

        Design: Corner/entities/flight_creation_computes_dry_operating_performance_and_allowed_payload
        """
        world = fx.reference_world(compartment_specs=[])

        response = api_client.create_flight(
            F.flight_payload(world.aircraft_id, world.runway_id, world.program_id),
            LOAD_CONTROLLER,
        )

        flight = get_success_data(response, 201)
        A.assert_flight_capacity(
            flight,
            dry_operating_weight_kg=42550.00,
            dry_operating_index=62.53,
            performance_limited_takeoff_weight_kg=73810.00,
            allowed_payload_kg=20180.00,
            limiting_factor="MZFW",
        )
        A.assert_flight_state(
            flight, status="PLANNING", load_release_state="OPEN", dg_hold_count=0
        )


class TestServerGeneratedSystemFields:
    def test_every_create_stamps_its_own_id_version_and_timestamps(self):
        """Two rows created in one run carry version 1 and distinct identifiers.

        PRD: "Every resource also carries `created_at` and `updated_at`, both ISO
        8601 UTC timestamps with three fractional digits, and `version`, an integer
        that begins at 1 when the row is created."

        Design: Corner/entities/system_fields_id_version_and_timestamps_are_server_generated
        """
        fx.position_clock()

        standard = fx.create_weight_program()
        actual = fx.create_actual_weight_program()

        for program in (standard, actual):
            A.assert_version_is(program, 1)
            assert program["created_at"] == program["updated_at"], (
                "a freshly created row should have identical timestamps"
            )
            assert program["id"], "the server should mint an identifier"
        assert standard["status"] == "ACTIVE", "a published programme should read ACTIVE"
        assert standard["id"] != actual["id"], "two rows should carry different identifiers"


class TestTypeConstraints:
    def test_a_bad_enum_a_negative_limit_and_a_zero_weight_are_all_refused(self):
        """Three shape faults on two surfaces, none of which reaches a later rung.

        PRD: "Request shape — every required input field present, every enum value
        a declared member, every weight, length and count field at least 0, with
        consignment `weight_kg` and compartment `length_m` required to be strictly
        greater than 0, and `limit` within 1 through 100 with `offset` at least 0 on
        list endpoints; otherwise `ERR_INVALID_REQUEST`, 400. Applies to every
        endpoint."

        Design: Corner/entities/compartment_and_cargo_type_constraints_reject_bad_enums_and_quantities
        """
        world = fx.reference_world(
            compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.flight_world(world, flight_number="LX1602")

        validate_error(
            api_client.create_compartment(
                F.compartment_payload(
                    world.aircraft_id, "BX", "BULK_LOCKER", 24.6, 5000, 900, 6.0
                ),
                ADMIN,
            ),
            E.INVALID_REQUEST,
            400,
        )
        validate_error(
            api_client.create_compartment(
                F.compartment_payload(world.aircraft_id, "H4", "HOLD", 24.6, 5000, -900, 6.0),
                ADMIN,
            ),
            E.INVALID_REQUEST,
            400,
        )
        validate_error(
            api_client.create_cargo_item(
                F.cargo_item_payload(world.flight_id, "724-90000001", weight_kg=0, length_m=1.2),
                RAMP_AGENT,
            ),
            E.INVALID_REQUEST,
            400,
        )

        rows, meta = validate_paginated(
            api_client.list_aircraft_compartments(world.aircraft_id, ADMIN)
        )
        A.assert_pagination_meta(meta, total_count=0)
        rows, meta = validate_paginated(
            api_client.list_cargo_items(RAMP_AGENT, {"flight_id": world.flight_id})
        )
        A.assert_pagination_meta(meta, total_count=0)


class TestUnknownParent:
    def test_a_compartment_offered_to_an_unknown_airframe_is_not_found(self):
        """The body's foreign key is checked before any uniqueness constraint.

        PRD: "Body foreign-key existence — every foreign key in the request body
        resolves; otherwise the matching not-found error, 404."

        Design: Corner/entities/compartment_creation_with_unknown_parent_aircraft_not_found
        """
        aircraft = fx.create_aircraft("HB-AAA")

        response = api_client.create_compartment(
            F.compartment_payload(
                "00000000-0000-0000-0000-0000000000c9", "H4", "HOLD", 24.6, 5000, 900, 6.0
            ),
            ADMIN,
        )

        validate_error(response, E.AIRCRAFT_NOT_FOUND, 404)
        rows, meta = validate_paginated(
            api_client.list_aircraft_compartments(str(aircraft["id"]), ADMIN)
        )
        A.assert_pagination_meta(meta, total_count=0)


class TestCrossAircraftCompartment:
    def test_a_cabin_zone_of_another_airframe_cannot_be_seated(self):
        """The kind is right, so only the ownership rule can be the refusal.

        PRD: "Compartment belongs to the right airframe — the referenced
        compartment's `aircraft_id` must equal the `aircraft_id` of the flight
        owning the plan, consignment or sheet being modified; otherwise
        `ERR_COMPARTMENT_NOT_ON_AIRCRAFT`, 422, on passenger-line creation,
        bag-allocation creation, consignment stowage, gate-bag presentation and
        last-minute-change recording."

        Design: Corner/entities/cross_aircraft_compartment_on_a_pax_line_is_refused
        """
        world = fx.reference_world(
            compartment_specs=_layout("OC"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        sibling = fx.sibling_airframe_world(world, compartment_specs=_layout("OC"))
        fx.plan_world(world, flight_overrides={"flight_number": "LX1602"})

        response = api_client.create_pax_line(
            F.pax_line_payload(
                world.plan_id,
                sibling.compartment_id("OC"),
                male_count=25,
                female_count=35,
            ),
            LOAD_CONTROLLER,
        )

        validate_error(response, E.COMPARTMENT_NOT_ON_AIRCRAFT, 422)
        rows, meta = validate_paginated(
            api_client.list_pax_lines(LOAD_CONTROLLER, {"load_plan_id": world.plan_id})
        )
        A.assert_pagination_meta(meta, total_count=0)
        A.assert_plan_figures(fx.refresh_plan(world), status="DRAFT")
