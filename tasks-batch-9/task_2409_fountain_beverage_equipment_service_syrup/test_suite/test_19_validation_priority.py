"""The validation ladder: which of two broken rules answers the caller.

Each test breaks two rules at once and pins the rung that speaks, plus the two gates
that only fire under a condition and the two boundary cases that pass rather than fail.
"""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    activate_agreement,
    add_stop,
    add_telemetry,
    allocate,
    allocation_payload,
    ApiErrorId,
    arrive_stop,
    assess_shortfall_payload,
    create_agreement,
    create_dispenser_unit_payload,
    create_outlet,
    create_position,
    create_route,
    create_route_stop_payload,
    create_supply_item,
    create_task,
    create_telemetry_payload,
    create_unit,
    complete_task,
    create_call,
    dispatch_call_payload,
    dispatch_route,
    pin_clock,
    place_compliance_hold,
    read_call,
    read_outlet,
    read_position,
    read_route,
    read_stop,
    read_unit,
    recall_decision_payload,
    route_version,
    run_forecast,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]
DRIVER = TEST_USERS["driver_headers"]
TECH = TEST_USERS["technician_headers"]
OFFICER = TEST_USERS["officer_headers"]

CLOCK = "2026-08-01T00:00:00Z"
UNKNOWN_OUTLET_ID = "00000000-0000-0000-0000-0000000000ee"


def _outlet():
    pin_clock(CLOCK)
    return create_outlet(
        name="Riverside Diner", account_code="OUT-1001", region_code="R-WEST"
    )


def _outlet_agreement_and_unit(activate=False, equipment_value_cents=480000,
                               installed_at="2025-11-01T00:00:00Z"):
    outlet = _outlet()
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=8000,
        equipment_value_cents=equipment_value_cents,
    )
    unit = create_unit(
        outlet["id"], agreement["id"],
        serial_number="SN-9001", installed_at=installed_at,
    )
    if activate:
        activate_agreement(agreement["id"])
    return outlet, agreement, unit


def _cola_sku(**overrides):
    catalogue_entry = {
        "sku_code": "SKU-COLA",
        "brand_name": "Cola Classic",
        "supply_form": "CARTRIDGE",
        "case_pack_units": 4,
        "ounces_per_unit": 1000,
        "national_allocation_units": 100,
    }
    catalogue_entry.update(overrides)
    return create_supply_item(**catalogue_entry)


def _arrived_stop_with_an_allocation(capacity_units=60, unit_count=1):
    """A dispatched route whose only stop has been arrived at holding twelve units."""
    outlet, agreement, unit = _outlet_agreement_and_unit()
    units = [unit]
    for index in range(2, unit_count + 1):
        units.append(
            create_unit(
                outlet["id"], agreement["id"],
                serial_number=f"SN-900{index}",
                installed_at="2025-11-01T00:00:00Z",
            )
        )
    item = _cola_sku()
    add_telemetry(unit["id"], item["id"], 7000, "2026-07-28T00:00:00Z", window_days=7)
    position = create_position(outlet["id"], item["id"], 2)
    run_forecast(position["id"], "TRAILING_ACTUAL", 7)
    route = create_route(
        route_code="RT-01", depot_region_code="R-WEST",
        service_date="2026-08-03T00:00:00Z", van_code="VAN-7",
        capacity_units=capacity_units,
    )
    stop = add_stop(
        route["id"], outlet["id"], 1, "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z"
    )
    allocate(stop["id"], [position["id"]])
    return outlet, units, position, route, stop


class TestLadderOrder:
    def test_the_role_gate_answers_before_the_body_is_read(self, api):
        """PRD §2.6: "Checks are evaluated in the following priority order, and the first
        failure terminates the request. Nothing is persisted when a request fails at any
        rung of this ladder." The second rung is the role gate: "The acting role appears in
        the target endpoint's role list, otherwise `ERR_UNAUTHORIZED` (403). Applies to
        every endpoint."

        Design: Corner/validations/unauthorized_role_outranks_the_malformed_body
        """
        pin_clock(CLOCK)

        validate_error(
            api.create_outlet(
                {"name": "Riverside Diner", "region_code": "R-WEST"}, DRIVER
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        outlets, _meta = validate_paginated(api.list_outlets(ADMIN))
        assert outlets == []

    def test_a_negative_index_answers_before_the_unknown_route_is_looked_up(self, api):
        """PRD §2.6: "The body parses, every required input field is present, every
        enum-valued field carries a declared member, numeric fields respect their declared
        ranges (no negative units, ounces, gallons or capacities), and any supplied `limit`
        lies between 1 and 100 inclusive. Otherwise `ERR_INVALID_REQUEST` (400). Applies
        to every endpoint." Path resolution is the rung below it: "Every identifier in the
        request path must resolve to an existing row, validated strictly left to right, so
        the leftmost unresolvable identifier decides the error."

        Design: Corner/validations/malformed_body_outranks_the_unknown_path_id
        """
        outlet = _outlet()
        route = create_route(
            route_code="RT-01", depot_region_code="R-WEST",
            service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
        )

        validate_error(
            api.create_route_stop(
                NON_EXISTENT_UUID,
                create_route_stop_payload(
                    outlet["id"], route["version"], -1,
                    "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        stops, _meta = validate_paginated(api.list_route_stops(PLANNER))
        assert stops == []

    def test_the_unknown_path_route_answers_before_the_unknown_body_outlet(self, api):
        """PRD §2.6: "Every identifier in the request path must resolve to an existing row,
        validated strictly left to right, so the leftmost unresolvable identifier decides
        the error." Only then do body references resolve: "Every foreign reference named in
        the body — `outlet_id`, `agreement_id`, `dispenser_unit_id`, `supply_item_id`, and
        every member of `supply_position_ids` — must resolve, otherwise the corresponding
        404 code above is returned."

        Design: Corner/validations/unknown_path_id_outranks_the_unknown_body_foreign_key
        """
        pin_clock(CLOCK)
        route = create_route(
            route_code="RT-01", depot_region_code="R-WEST",
            service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
        )

        validate_error(
            api.create_route_stop(
                NON_EXISTENT_UUID,
                create_route_stop_payload(
                    UNKNOWN_OUTLET_ID, route["version"], 1,
                    "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_ROUTE_NOT_FOUND,
            404,
        )

    def test_the_stale_route_version_answers_before_the_wrong_region(self, api):
        """PRD §2.6: "`expected_route_version` must equal the stored `version` of the
        replenishment route, otherwise `ERR_STALE_ROUTE_VERSION` (412). This rung guards
        `POST /fountain-network/replenishment-routes/{id}/stops`,
        `POST /fountain-network/replenishment-routes/{id}/dispatch` and
        `POST /fountain-network/replenishment-routes/{id}/cancel`." Region coherence sits
        far below it: "The stop outlet's `region_code` must equal the route's
        `depot_region_code`, otherwise `ERR_REGION_MISMATCH` (422) on
        `POST /fountain-network/replenishment-routes/{id}/stops`."

        Design: Corner/validations/stale_route_version_outranks_the_region_mismatch
        """
        home = _outlet()
        away = create_outlet(
            name="Harbor Cafe", account_code="OUT-1002", region_code="R-EAST"
        )
        route = create_route(
            route_code="RT-01", depot_region_code="R-WEST",
            service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
        )
        stale_version = route["version"]
        first = add_stop(
            route["id"], home["id"], 1,
            "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
        )
        assert route_version(route["id"]) != stale_version

        validate_error(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(
                    away["id"], stale_version, 2,
                    "2026-08-03T11:00:00Z", "2026-08-03T12:00:00Z",
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_STALE_ROUTE_VERSION,
            412,
        )

        stops, _meta = validate_paginated(
            api.list_route_stops(PLANNER, {"route_id": route["id"]})
        )
        assert [stop["id"] for stop in stops] == [first["id"]]

    def test_the_illegal_transition_answers_before_the_identity_of_the_technician(self, api):
        """PRD §2.6: "The target resource must currently sit in a state from which the
        requested transition is declared in §3." The dispatch-holder rung comes two below
        it: "Arriving on site, resolving and escalating must be performed by the technician
        holding the current dispatch, that is `X-User-ID` equal to `assigned_tech_user_id`;
        otherwise `ERR_TECHNICIAN_NOT_ASSIGNED` (403)."

        Design: Corner/validations/invalid_state_transition_outranks_the_technician_identity_check
        """
        _outlet_row, _agreement, unit = _outlet_agreement_and_unit()
        call = create_call(unit["id"], "ICE_FAULT", CLOCK)

        validate_error(
            api.arrive_on_site(call["id"], TECH),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        untouched = read_call(call["id"])
        assert untouched["status"] == "OPEN"
        assert untouched["assigned_tech_user_id"] is None

    def test_the_staged_machine_answers_before_the_missing_van_part(self, api):
        """PRD §2.6: "A service call may only be opened or dispatched while its dispenser
        unit's `status` is `IN_SERVICE` or `SERVICE_HOLD`; a `RECALL_STAGED` or `RETURNED`
        unit yields `ERR_UNIT_NOT_SERVICEABLE` (409) on
        `POST /fountain-network/service-calls` and
        `POST /fountain-network/service-calls/{id}/dispatch`." The parts rung is far below:
        "When `part_sku` is supplied, a van stock row must exist for that van and that
        part, otherwise `ERR_PART_NOT_ON_VAN` (404) on
        `POST /fountain-network/service-calls/{id}/dispatch`."

        Design: Corner/validations/unit_not_serviceable_outranks_the_missing_van_part
        """
        _outlet_row, agreement, unit = _outlet_agreement_and_unit(
            activate=True, equipment_value_cents=450000,
            installed_at="2026-07-20T00:00:00Z",
        )
        call = create_call(unit["id"], "NO_POUR", CLOCK)
        validate_success(
            api.assess_shortfall(
                agreement["id"],
                assess_shortfall_payload(
                    "2026-07-01T00:00:00Z", "2026-10-01T00:00:00Z",
                    exposure_variant="BOOK_VALUE",
                ),
                ADMIN,
            )
        )
        validate_success(
            api.recall_decision(
                agreement["id"], recall_decision_payload("RECALL"), OFFICER
            )
        )
        assert read_unit(unit["id"])["status"] == "RECALL_STAGED"

        validate_error(
            api.dispatch_service_call(
                call["id"],
                dispatch_call_payload(
                    "VAN-7", "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z",
                    part_sku="PUMP_ASSY_12", part_units=1,
                ),
                TECH,
            ),
            ApiErrorId.ERR_UNIT_NOT_SERVICEABLE,
            409,
        )

        untouched = read_call(call["id"])
        assert untouched["status"] == "OPEN"
        assert untouched["van_code"] is None

    def test_the_frozen_posture_answers_before_the_off_ratio_machine(self, api):
        """PRD §3.7: "Serving carries two safety gates that fire before anything moves. If
        the outlet's `service_posture` is `FROZEN`, service is refused with
        `ERR_OUTLET_POSTURE_FROZEN`." §2.6 pins which of the two speaks: "The outlet's
        `service_posture` must not be `FROZEN`, otherwise `ERR_OUTLET_POSTURE_FROZEN`
        (409). This rung guards two operations:
        `POST /fountain-network/route-stops/{id}/allocations` and
        `POST /fountain-network/route-stops/{id}/serve`."

        Design: Corner/validations/frozen_posture_outranks_the_out_of_spec_calibration_on_serve
        """
        outlet, units, position, route, stop = _arrived_stop_with_an_allocation()
        calibration = create_task(
            units[0]["id"], "BRIX_CALIBRATION", "2026-08-20T00:00:00Z"
        )
        complete_task(calibration["id"], TECH, measured_brix_ratio=5.40)
        dispatch_route(route["id"])
        arrive_stop(stop["id"])
        place_compliance_hold(
            outlet["id"], OFFICER, hold_reason_code="SANITATION_LAPSE"
        )
        assert read_outlet(outlet["id"])["service_posture"] == "FROZEN"
        assert read_unit(units[0]["id"])["calibration_status"] == "OUT_OF_SPEC"

        validate_error(
            api.serve_stop(stop["id"], DRIVER),
            ApiErrorId.ERR_OUTLET_POSTURE_FROZEN,
            409,
        )

        assert read_stop(stop["id"])["status"] == "ARRIVED"
        assert read_position(position["id"])["on_hand_units"] == 2

    def test_the_unknown_agreement_answers_before_the_duplicate_serial(self, api):
        """PRD §2.6: "Every foreign reference named in the body — `outlet_id`,
        `agreement_id`, `dispenser_unit_id`, `supply_item_id`, and every member of
        `supply_position_ids` — must resolve, otherwise the corresponding 404 code above is
        returned." Uniqueness is rung 30: "An outlet's `account_code`, a dispenser's
        `serial_number`, a supply item's `sku_code`, a route's `route_code`, the
        outlet-and-SKU pair behind a supply position, the van-and-part pair behind a van
        stock row, and a stop's `sequence_index` within its route are each unique."

        Design: Corner/validations/foreign_key_resolution_runs_before_the_duplicate_serial_check
        """
        outlet, _agreement, _unit = _outlet_agreement_and_unit()

        validate_error(
            api.create_dispenser_unit(
                create_dispenser_unit_payload(
                    outlet["id"], NON_EXISTENT_UUID,
                    serial_number="SN-9001", installed_at="2025-11-01T00:00:00Z",
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_AGREEMENT_NOT_FOUND,
            404,
        )

        units, _meta = validate_paginated(api.list_dispenser_units(ADMIN))
        assert len(units) == 1


class TestCrossEntityGates:
    def test_a_sibling_machine_out_of_spec_blocks_the_delivery(self, api):
        """PRD §2.6: "No dispenser unit at the stop's outlet may carry `calibration_status`
        equal to `OUT_OF_SPEC`, otherwise `ERR_CALIBRATION_OUT_OF_SPEC` (409) on
        `POST /fountain-network/route-stops/{id}/serve`." §3.7 gives the reason: "If any
        dispenser unit at that outlet carries `calibration_status` `OUT_OF_SPEC`, service
        is refused with `ERR_CALIBRATION_OUT_OF_SPEC` — the network will not top up a
        machine that is pouring off-ratio product."

        Design: Corner/validations/serve_blocked_by_an_out_of_spec_sibling_unit_at_the_same_outlet
        """
        outlet, units, _position, route, stop = _arrived_stop_with_an_allocation(
            unit_count=2
        )
        good = create_task(units[0]["id"], "BRIX_CALIBRATION", "2026-08-20T00:00:00Z")
        complete_task(good["id"], TECH, measured_brix_ratio=5.00)
        bad = create_task(units[1]["id"], "BRIX_CALIBRATION", "2026-08-20T00:00:00Z")
        complete_task(bad["id"], TECH, measured_brix_ratio=5.40)
        dispatch_route(route["id"])
        arrive_stop(stop["id"])
        assert read_unit(units[0]["id"])["calibration_status"] == "IN_SPEC"
        assert read_unit(units[1]["id"])["calibration_status"] == "OUT_OF_SPEC"
        assert read_outlet(outlet["id"])["service_posture"] == "OPEN"

        validate_error(
            api.serve_stop(stop["id"], DRIVER),
            ApiErrorId.ERR_CALIBRATION_OUT_OF_SPEC,
            409,
        )

        assert read_stop(stop["id"])["status"] == "ARRIVED"

    def test_the_second_stop_finds_the_van_already_full(self, api):
        """PRD §2.6: "For each eligible position, the route's remaining capacity — its
        `capacity_units` less its `committed_units` — must be at least one
        `case_pack_units`, otherwise `ERR_ROUTE_CAPACITY_EXCEEDED` (409) on the same
        endpoint." §3.7 says when that capacity is read: "The SKU's unreserved pool is its
        `national_allocation_units` less its `reserved_pool_units`, and the route's
        remaining capacity is its `capacity_units` less its `committed_units`, both read at
        the moment this position is reached, so earlier grants in the same request have
        already consumed what they took."

        Design: Corner/validations/route_capacity_exhausted_by_the_second_stop_of_the_same_route
        """
        outlet, _agreement, unit = _outlet_agreement_and_unit()
        cola = _cola_sku()
        lemon = _cola_sku(sku_code="SKU-LEMON", brand_name="Lemon Fizz")
        for item in (cola, lemon):
            add_telemetry(
                unit["id"], item["id"], 7000, "2026-07-28T00:00:00Z", window_days=7
            )
        first_position = create_position(outlet["id"], cola["id"], 2)
        second_position = create_position(outlet["id"], lemon["id"], 2)
        run_forecast(first_position["id"], "TRAILING_ACTUAL", 7)
        run_forecast(second_position["id"], "TRAILING_ACTUAL", 7)
        route = create_route(
            route_code="RT-01", depot_region_code="R-WEST",
            service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=12,
        )
        first_stop = add_stop(
            route["id"], outlet["id"], 1,
            "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
        )
        second_stop = add_stop(
            route["id"], outlet["id"], 2,
            "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z",
        )
        allocate(first_stop["id"], [first_position["id"]])
        assert read_position(first_position["id"])["allocated_units"] == 12

        validate_error(
            api.allocate_stop(
                second_stop["id"], allocation_payload([second_position["id"]]), PLANNER
            ),
            ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED,
            409,
        )

        refused = read_position(second_position["id"])
        assert refused["allocated_units"] == 0
        assert refused["planned_route_stop_id"] is None
        assert read_route(route["id"])["committed_units"] == 12


class TestGatesThatDoNotFire:
    def test_a_dispatch_that_asks_for_no_part_never_looks_at_a_van(self, api):
        """PRD §2.6: "When `part_sku` is supplied, a van stock row must exist for that van
        and that part, otherwise `ERR_PART_NOT_ON_VAN` (404) on
        `POST /fountain-network/service-calls/{id}/dispatch`." The next rung is guarded the
        same way: "The selected van stock row must hold at least as many `on_van_units` as
        the requested `part_units`, otherwise `ERR_INSUFFICIENT_VAN_PARTS` (409) on
        `POST /fountain-network/service-calls/{id}/dispatch`."

        Design: Corner/validations/dispatch_without_a_part_sku_skips_both_van_parts_checks
        """
        _outlet_row, _agreement, unit = _outlet_agreement_and_unit()
        call = create_call(unit["id"], "CO2_LOW", CLOCK)

        dispatched = validate_success(
            api.dispatch_service_call(
                call["id"],
                dispatch_call_payload(
                    "VAN-7", "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z"
                ),
                TECH,
            )
        )
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["van_code"] == "VAN-7"
        assert dispatched["assigned_tech_user_id"] == TECH["X-User-ID"]
        assert dispatched["reserved_part_units"] == 0
        assert dispatched["reserved_part_stock_id"] is None

        stocks, _meta = validate_paginated(api.list_van_part_stocks(ADMIN))
        assert stocks == []

    def test_a_term_ending_on_this_instant_may_be_closed(self, api):
        """PRD §2.6: "The logical clock must be at or past the agreement's `term_end_date`,
        otherwise `ERR_TERM_NOT_ELAPSED` (409) on
        `POST /fountain-network/placement-agreements/{id}/close-term`." §3.2 states the move
        itself: "A `NetworkAdmin` closes the term of an `ACTIVE` agreement, moving it
        `ACTIVE → EXPIRED` and incrementing its `version` by one, but only once the logical
        clock has reached or passed the agreement's `term_end_date`; attempting it earlier
        is `ERR_TERM_NOT_ELAPSED`."

        Design: Corner/validations/close_term_exactly_at_the_term_end_date_passes
        """
        outlet = _outlet()
        agreement = create_agreement(
            outlet["id"],
            term_start_date="2026-01-01T00:00:00Z",
            term_end_date="2026-08-01T00:00:00Z",
            annual_commitment_gallons=8000,
            equipment_value_cents=480000,
        )
        unit = create_unit(
            outlet["id"], agreement["id"],
            serial_number="SN-9001", installed_at="2025-11-01T00:00:00Z",
        )
        activate_agreement(agreement["id"])

        closed = validate_success(api.close_term(agreement["id"], ADMIN))
        assert closed["status"] == "EXPIRED"
        assert read_unit(unit["id"])["status"] == "IN_SERVICE"
        assert read_outlet(outlet["id"])["status"] == "ACTIVE"


class TestTemporalGate:
    def test_a_reading_stamped_on_the_clock_is_stored_but_a_second_later_is_not(self, api):
        """PRD §2.6: "`reading_at` on a telemetry reading and `reported_at` on a service
        call must be at or before the logical clock; a later instant yields
        `ERR_TIMESTAMP_IN_FUTURE` (422) on `POST /fountain-network/telemetry-readings` and
        `POST /fountain-network/service-calls`." Only the accepted reading moves the
        odometer, per §3.4: "Each ingestion refreshes the receiving machine's
        `lifetime_dispensed_gallons`, which is defined as the total ounces ever reported for
        that unit divided by 128 and then rounded half up to two decimal places."

        Design: Corner/validations/telemetry_at_the_clock_accepted_but_one_second_later_rejected
        """
        _outlet_row, _agreement, unit = _outlet_agreement_and_unit()
        item = _cola_sku()
        add_telemetry(unit["id"], item["id"], 128, CLOCK, window_days=7)

        validate_error(
            api.create_telemetry_reading(
                create_telemetry_payload(
                    unit["id"], item["id"], 128, "2026-08-01T00:00:01Z", window_days=7
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_TIMESTAMP_IN_FUTURE,
            422,
        )

        assert read_unit(unit["id"])["lifetime_dispensed_gallons"] == pytest.approx(
            1.00, abs=0.01
        )
        readings, _meta = validate_paginated(api.list_telemetry_readings(PLANNER))
        assert len(readings) == 1
