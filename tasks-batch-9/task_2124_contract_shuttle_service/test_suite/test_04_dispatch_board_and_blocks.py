"""Binding buses and drivers to trips: safety gates, interval geometry, duty caps."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_contract,
    create_driver,
    create_maintenance_order,
    create_vehicle,
    add_single_departure_route,
    close_maintenance_order,
    set_clock,
    setup_assigned_trip,
    setup_driver_overlap_scenario,
    setup_duty_cap_scenario,
    setup_layover_gap_scenario,
    setup_single_trip_scenario,
    setup_touching_intervals_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["contract_admin_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]
PLANNER = TEST_USERS["ops_planner_headers"]

BAD_VEHICLE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BAD_DRIVER_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _assign(api, trip_id, vehicle_id, driver_id):
    return api.assign_trip(
        trip_id, {"vehicle_id": vehicle_id, "driver_id": driver_id}, PLANNER
    )


# ─── The compensating pair ────────────────────────────────────────────────────

def test_assign_raises_committed_block_by_the_buffered_duration(api):
    """PRD §3.3: "It is the sum, over every trip pointing at that vehicle whose
    `dispatch_status` is `ASSIGNED`, `IN_SERVICE` or `COMPLETED` across all service
    dates, of that trip's scheduled duration plus a fixed twelve-minute layover
    buffer; a trip's scheduled duration is its `scheduled_arrival_min` minus its
    `scheduled_departure_min`."
    PRD §3.4: "A successful assignment writes `vehicle_id` and `driver_id` onto the
    trip, recomputes `committed_block_minutes` on the vehicle and
    `assigned_duty_minutes_current_date` on the driver, and increments the trip's
    `version` by one."

    Design: Difficulty/compensating_invariant/trip_unassign_restores_vehicle_block_minutes
    """
    scenario = setup_single_trip_scenario(
        clock="2026-09-02T05:00:00Z", service_date="2026-09-02",
        departure_min=420, loop_minutes=48,
        contract_overrides={"client_name": "Block Minutes Campus", "site_type": "CAMPUS"},
    )
    before = validate_success(api.get_vehicle(scenario["vehicle"]["id"], FLEET))
    assert before["committed_block_minutes"] == 0

    assigned = validate_success(
        _assign(api, scenario["trip"]["id"], scenario["vehicle"]["id"], scenario["driver"]["id"])
    )
    assert assigned["dispatch_status"] == "ASSIGNED"

    during = validate_success(api.get_vehicle(scenario["vehicle"]["id"], FLEET))
    assert during["committed_block_minutes"] == 60, (
        "48 loop minutes plus the twelve-minute layover buffer, got "
        f"{during['committed_block_minutes']}"
    )

    driver = validate_success(api.get_driver(scenario["driver"]["id"], PLANNER))
    assert driver["assigned_duty_minutes_current_date"] == 48, (
        "a driver's duty carries no layover buffer"
    )


def test_unassign_restores_committed_block_minutes_exactly(api):
    """PRD §3.4: "The release clears `vehicle_id` and `driver_id`, recomputes
    `committed_block_minutes` on the released vehicle — which, because the
    recomputation is a full scan rather than a delta, restores it to precisely its
    pre-assignment value — and recomputes `assigned_duty_minutes_current_date` on
    the released driver."
    PRD §2.7: "every derived counter is a full recomputation from its source rows,
    never an incremental delta applied to a stored figure."

    Design: Difficulty/compensating_invariant/trip_unassign_restores_vehicle_block_minutes
    """
    scenario = setup_assigned_trip(
        clock="2026-09-02T05:00:00Z", service_date="2026-09-02",
        departure_min=420, loop_minutes=48,
        contract_overrides={"client_name": "Block Minutes Campus", "site_type": "CAMPUS"},
    )
    mid = validate_success(api.get_vehicle(scenario["vehicle"]["id"], FLEET))
    assert mid["committed_block_minutes"] == 60

    released = validate_success(api.unassign_trip(scenario["trip"]["id"], PLANNER))
    assert released["dispatch_status"] == "SCHEDULED"
    assert released.get("vehicle_id") is None
    assert released.get("driver_id") is None

    after = validate_success(api.get_vehicle(scenario["vehicle"]["id"], FLEET))
    assert after["committed_block_minutes"] == 0, (
        "the conserved quantity returns to exactly its pre-assignment value, got "
        f"{after['committed_block_minutes']}"
    )

    driver = validate_success(api.get_driver(scenario["driver"]["id"], PLANNER))
    assert driver["assigned_duty_minutes_current_date"] == 0


def test_unassigning_a_scheduled_trip_is_rejected(api):
    """PRD §3.4: "It is permitted only from `ASSIGNED`, moving the trip back
    `ASSIGNED` → `SCHEDULED`; from any other dispatch state it is rejected with
    `ERR_TRIP_NOT_ASSIGNED`."

    Design: Corner/state_machines/unassign_a_scheduled_trip_returns_trip_not_assigned
    """
    scenario = setup_single_trip_scenario(contract_overrides={"client_name": "Unassign Guard"})

    response = api.unassign_trip(scenario["trip"]["id"], PLANNER)
    validate_error(response, ApiErrorId.ERR_TRIP_NOT_ASSIGNED.value, 409)

    trip = validate_success(api.get_trip(scenario["trip"]["id"], PLANNER))
    assert trip["dispatch_status"] == "SCHEDULED"


# ─── The layover buffer boundary ──────────────────────────────────────────────

def test_eleven_minute_layover_gap_is_rejected(api):
    """PRD §3.4: "A trip's buffered block is the half-open interval that starts at
    its `scheduled_departure_min` and ends at its `scheduled_arrival_min` plus the
    twelve-minute layover buffer, with the end point excluded. Because the end point
    is excluded, two trips need a gap of at least twelve minutes between one arrival
    and the next departure, and a gap of exactly twelve minutes passes. An overlap
    is rejected with `ERR_VEHICLE_BLOCK_CONFLICT` and HTTP 409."

    Design: Difficulty/boundary_precision_check/layover_buffer_exactly_twelve_minutes
    """
    scenario = setup_layover_gap_scenario()

    response = _assign(
        api, scenario["trip_479"]["id"], scenario["vehicle"]["id"], scenario["driver"]["id"]
    )
    validate_error(response, ApiErrorId.ERR_VEHICLE_BLOCK_CONFLICT.value, 409)

    trip = validate_success(api.get_trip(scenario["trip_479"]["id"], PLANNER))
    assert trip["dispatch_status"] == "SCHEDULED"
    assert trip.get("vehicle_id") is None


def test_twelve_minute_layover_gap_is_accepted(api):
    """PRD §3.4: "Because the end point is excluded, two trips need a gap of at
    least twelve minutes between one arrival and the next departure, and a gap of
    exactly twelve minutes passes."
    PRD §3.3: "It is the sum, over every trip pointing at that vehicle whose
    `dispatch_status` is `ASSIGNED`, `IN_SERVICE` or `COMPLETED` across all service
    dates, of that trip's scheduled duration plus a fixed twelve-minute layover
    buffer"

    Design: Difficulty/boundary_precision_check/layover_buffer_exactly_twelve_minutes
    """
    scenario = setup_layover_gap_scenario()

    accepted = validate_success(
        _assign(api, scenario["trip_480"]["id"], scenario["vehicle"]["id"],
                scenario["driver"]["id"])
    )
    assert accepted["dispatch_status"] == "ASSIGNED"

    bus = validate_success(api.get_vehicle(scenario["vehicle"]["id"], FLEET))
    assert bus["committed_block_minutes"] == 102, (
        "a 48-minute and a 30-minute trip, each plus the twelve-minute buffer, got "
        f"{bus['committed_block_minutes']}"
    )

    driver = validate_success(api.get_driver(scenario["driver"]["id"], PLANNER))
    assert driver["assigned_duty_minutes_current_date"] == 0, (
        "the clock's date is 2026-09-01 while both trips run on 2026-09-02"
    )


# ─── Buffered vehicle block versus unbuffered driver interval ─────────────────

def test_touching_trips_conflict_on_the_buffered_vehicle_block(api):
    """PRD §3.4: "No other trip already assigned to this vehicle on this
    `service_date` may overlap the candidate's buffered block. A trip's buffered
    block is the half-open interval that starts at its `scheduled_departure_min` and
    ends at its `scheduled_arrival_min` plus the twelve-minute layover buffer, with
    the end point excluded."

    Design: Difficulty/resource_temporal_overlap/vehicle_buffered_block_versus_driver_adjacency
    """
    scenario = setup_touching_intervals_scenario()

    response = _assign(
        api, scenario["trip_touching"]["id"], scenario["vehicle_a"]["id"],
        scenario["driver"]["id"],
    )
    validate_error(response, ApiErrorId.ERR_VEHICLE_BLOCK_CONFLICT.value, 409)

    trip = validate_success(api.get_trip(scenario["trip_touching"]["id"], PLANNER))
    assert trip["dispatch_status"] == "SCHEDULED"


def test_touching_trips_are_accepted_for_one_driver(api):
    """PRD §3.4: "No other trip already assigned to this driver on the same
    `service_date` may overlap the candidate's unbuffered interval, which runs from
    `scheduled_departure_min` up to but not including `scheduled_arrival_min`.
    Drivers carry no layover buffer, so touching endpoints — one trip's arrival
    exactly equal to the next trip's departure — are permitted."
    PRD §3.3: "It is the sum, over every trip pointing at that vehicle whose
    `dispatch_status` is `ASSIGNED`, `IN_SERVICE` or `COMPLETED` across all service
    dates, of that trip's scheduled duration plus a fixed twelve-minute layover
    buffer"
    PRD §3.4: "It is the sum, over every trip whose `driver_id` is this driver,
    whose `service_date` equals the logical clock's current UTC calendar date, and
    whose `dispatch_status` is `ASSIGNED`, `IN_SERVICE` or `COMPLETED`, of that
    trip's `scheduled_arrival_min` minus its `scheduled_departure_min`."

    Design: Difficulty/resource_temporal_overlap/vehicle_buffered_block_versus_driver_adjacency
    """
    scenario = setup_touching_intervals_scenario()

    accepted = validate_success(
        _assign(api, scenario["trip_touching"]["id"], scenario["vehicle_b"]["id"],
                scenario["driver"]["id"])
    )
    assert accepted["dispatch_status"] == "ASSIGNED"
    assert accepted["vehicle_id"] == scenario["vehicle_b"]["id"]
    assert accepted["driver_id"] == scenario["driver"]["id"]

    first_bus = validate_success(api.get_vehicle(scenario["vehicle_a"]["id"], FLEET))
    assert first_bus["committed_block_minutes"] == 60

    second_bus = validate_success(api.get_vehicle(scenario["vehicle_b"]["id"], FLEET))
    assert second_bus["committed_block_minutes"] == 42

    driver = validate_success(api.get_driver(scenario["driver"]["id"], PLANNER))
    assert driver["assigned_duty_minutes_current_date"] == 78, (
        "48 plus 30 wheels-turning minutes on the clock's date, got "
        f"{driver['assigned_duty_minutes_current_date']}"
    )


def test_driver_block_conflict_on_a_true_overlap(api):
    """PRD §3.4: "No other trip already assigned to this driver on the same
    `service_date` may overlap the candidate's unbuffered interval, which runs from
    `scheduled_departure_min` up to but not including `scheduled_arrival_min`.
    Drivers carry no layover buffer, so touching endpoints — one trip's arrival
    exactly equal to the next trip's departure — are permitted. An overlap is
    rejected with `ERR_DRIVER_BLOCK_CONFLICT` and HTTP 409."

    Design: Corner/validations/driver_block_conflict_on_true_overlap
    """
    scenario = setup_driver_overlap_scenario()

    response = _assign(
        api, scenario["trip_overlapping"]["id"], scenario["vehicle_b"]["id"],
        scenario["driver"]["id"],
    )
    validate_error(response, ApiErrorId.ERR_DRIVER_BLOCK_CONFLICT.value, 409)

    trip = validate_success(api.get_trip(scenario["trip_overlapping"]["id"], PLANNER))
    assert trip["dispatch_status"] == "SCHEDULED"
    assert trip.get("driver_id") is None

    driver = validate_success(api.get_driver(scenario["driver"]["id"], PLANNER))
    assert driver["assigned_duty_minutes_current_date"] == 48

    bus = validate_success(api.get_vehicle(scenario["vehicle_b"]["id"], FLEET))
    assert bus["committed_block_minutes"] == 0


# ─── The daily duty cap ───────────────────────────────────────────────────────

def test_duty_total_one_minute_over_the_cap_is_rejected(api):
    """PRD §3.4: "The driver's total assigned duty minutes on the candidate trip's
    own `service_date`, counting the candidate trip itself, must be less than or
    equal to that driver's `max_duty_minutes_per_day`; a total exactly equal to the
    cap passes. Exceeding it is rejected with `ERR_DRIVER_DUTY_EXCEEDED` and HTTP
    422."

    Design: Difficulty/resource_temporal_overlap/driver_duty_cap_aggregate_over_service_date
    """
    scenario = setup_duty_cap_scenario()

    response = _assign(
        api, scenario["trip_30"]["id"], scenario["vehicle_b"]["id"],
        scenario["driver_77"]["id"],
    )
    validate_error(response, ApiErrorId.ERR_DRIVER_DUTY_EXCEEDED.value, 422)

    trip = validate_success(api.get_trip(scenario["trip_30"]["id"], PLANNER))
    assert trip["dispatch_status"] == "SCHEDULED"

    driver = validate_success(api.get_driver(scenario["driver_77"]["id"], PLANNER))
    assert driver["assigned_duty_minutes_current_date"] == 48


def test_duty_total_exactly_at_the_cap_is_accepted(api):
    """PRD §3.4: "The driver's total assigned duty minutes on the candidate trip's
    own `service_date`, counting the candidate trip itself, must be less than or
    equal to that driver's `max_duty_minutes_per_day`; a total exactly equal to the
    cap passes."
    PRD §3.4: "It is the sum, over every trip whose `driver_id` is this driver,
    whose `service_date` equals the logical clock's current UTC calendar date, and
    whose `dispatch_status` is `ASSIGNED`, `IN_SERVICE` or `COMPLETED`, of that
    trip's `scheduled_arrival_min` minus its `scheduled_departure_min`."

    Design: Difficulty/resource_temporal_overlap/driver_duty_cap_aggregate_over_service_date
    """
    scenario = setup_duty_cap_scenario()

    validate_success(api.unassign_trip(scenario["trip_48"]["id"], PLANNER))
    validate_success(
        _assign(api, scenario["trip_48"]["id"], scenario["vehicle_a"]["id"],
                scenario["driver_78"]["id"])
    )
    accepted = validate_success(
        _assign(api, scenario["trip_30"]["id"], scenario["vehicle_b"]["id"],
                scenario["driver_78"]["id"])
    )
    assert accepted["driver_id"] == scenario["driver_78"]["id"]
    assert accepted["dispatch_status"] == "ASSIGNED"

    at_cap = validate_success(api.get_driver(scenario["driver_78"]["id"], PLANNER))
    assert at_cap["assigned_duty_minutes_current_date"] == 78

    released = validate_success(api.get_driver(scenario["driver_77"]["id"], PLANNER))
    assert released["assigned_duty_minutes_current_date"] == 0


# ─── Ladder precedence: own state before ADA certification ────────────────────

def _ada_assignment_scenario():
    scenario = setup_single_trip_scenario(
        contract_overrides={"client_name": "Priority Hotel"},
        vehicle_overrides={"is_ada_accessible": True, "odometer_km": 7_000},
        driver_overrides={"full_name": "Ada Certified", "ada_certified": True},
    )
    scenario["uncertified_driver"] = create_driver(
        full_name="Not Certified", ada_certified=False
    )
    return scenario


def test_assigning_an_assigned_trip_reports_the_state_error_first(api):
    """PRD §2.6: "Every request is screened through the same ordered ladder of
    checks, and the ladder is evaluated strictly in the order given below. The first
    check that fails determines the response, and no later check is evaluated."
    PRD §3.4: "The `OpsPlanner` supplies `vehicle_id` and `driver_id`, and the trip
    moves `SCHEDULED` → `ASSIGNED`; a trip in any other dispatch state is rejected
    with `ERR_TRIP_NOT_SCHEDULABLE`."

    Design: Difficulty/priority_pair_validation_conflict/assign_state_beats_ada_certification_safety
    """
    scenario = _ada_assignment_scenario()
    validate_success(
        _assign(api, scenario["trip"]["id"], scenario["vehicle"]["id"],
                scenario["driver"]["id"])
    )

    response = _assign(
        api, scenario["trip"]["id"], scenario["vehicle"]["id"],
        scenario["uncertified_driver"]["id"],
    )
    validate_error(response, ApiErrorId.ERR_TRIP_NOT_SCHEDULABLE.value, 409)


def test_same_assignment_after_release_reports_the_ada_certification_error(api):
    """PRD §3.4: "When the named vehicle's `is_ada_accessible` is true, the named
    driver's `ada_certified` must also be true, failing which the assignment is
    rejected with `ERR_DRIVER_NOT_ADA_CERTIFIED` and HTTP 422. A driver who is
    certified may of course drive a non-accessible bus."

    Design: Difficulty/priority_pair_validation_conflict/assign_state_beats_ada_certification_safety
    """
    scenario = _ada_assignment_scenario()
    validate_success(
        _assign(api, scenario["trip"]["id"], scenario["vehicle"]["id"],
                scenario["driver"]["id"])
    )
    validate_success(api.unassign_trip(scenario["trip"]["id"], PLANNER))

    response = _assign(
        api, scenario["trip"]["id"], scenario["vehicle"]["id"],
        scenario["uncertified_driver"]["id"],
    )
    validate_error(response, ApiErrorId.ERR_DRIVER_NOT_ADA_CERTIFIED.value, 422)

    trip = validate_success(api.get_trip(scenario["trip"]["id"], PLANNER))
    assert trip["dispatch_status"] == "SCHEDULED"
    assert trip.get("driver_id") is None
    assert trip.get("vehicle_id") is None


# ─── Cross-entity state: the bus must be AVAILABLE ────────────────────────────

def _maintenance_gate_scenario():
    scenario = setup_single_trip_scenario(
        clock="2026-09-02T05:00:00Z", service_date="2026-09-02",
        contract_overrides={"client_name": "Maintenance Gate Hotel"},
        vehicle_overrides={"odometer_km": 8_000},
        driver_overrides={"full_name": "Nia Osei"},
    )
    scenario["order"] = create_maintenance_order(
        scenario["vehicle"]["id"], kind="PREVENTIVE", service_date="2026-09-02",
        window_start_min=600, window_end_min=660,
    )
    return scenario


def test_assign_is_refused_while_the_bus_is_in_the_shop(api):
    """PRD §3.4: "The named vehicle's `status` must be `AVAILABLE`; a bus that is
    `IN_MAINTENANCE` or `RETIRED` is rejected with `ERR_VEHICLE_UNAVAILABLE` and
    HTTP 409, and that rejection precedes every safety and scheduling check below."

    Design: Difficulty/cross_entity_state_dependency/assign_blocked_by_vehicle_in_maintenance
    """
    scenario = _maintenance_gate_scenario()
    assert scenario["order"]["displaced_trip_count"] == 0, (
        "the 600..660 window does not intersect the 420..468 trip"
    )

    bus = validate_success(api.get_vehicle(scenario["vehicle"]["id"], FLEET))
    assert bus["status"] == "IN_MAINTENANCE"

    response = _assign(
        api, scenario["trip"]["id"], scenario["vehicle"]["id"], scenario["driver"]["id"]
    )
    validate_error(response, ApiErrorId.ERR_VEHICLE_UNAVAILABLE.value, 409)

    trip = validate_success(api.get_trip(scenario["trip"]["id"], PLANNER))
    assert trip["dispatch_status"] == "SCHEDULED"


def test_same_assign_succeeds_once_the_order_returns_the_bus(api):
    """PRD §3.3: "With `outcome` `RETURN_TO_SERVICE`, a vehicle currently
    `IN_MAINTENANCE` moves back to `AVAILABLE` and its `version` increments by one."
    PRD §3.4: "The named vehicle's `status` must be `AVAILABLE`; a bus that is
    `IN_MAINTENANCE` or `RETIRED` is rejected with `ERR_VEHICLE_UNAVAILABLE` and
    HTTP 409, and that rejection precedes every safety and scheduling check below."

    Design: Difficulty/cross_entity_state_dependency/assign_blocked_by_vehicle_in_maintenance
    """
    scenario = _maintenance_gate_scenario()
    close_maintenance_order(scenario["order"]["id"], "RETURN_TO_SERVICE")

    bus = validate_success(api.get_vehicle(scenario["vehicle"]["id"], FLEET))
    assert bus["status"] == "AVAILABLE"

    assigned = validate_success(
        _assign(api, scenario["trip"]["id"], scenario["vehicle"]["id"],
                scenario["driver"]["id"])
    )
    assert assigned["dispatch_status"] == "ASSIGNED"

    reread = validate_success(api.get_vehicle(scenario["vehicle"]["id"], FLEET))
    assert reread["committed_block_minutes"] == 60

    orders, _ = validate_paginated(
        api.list_vehicle_maintenance_orders(scenario["vehicle"]["id"], FLEET)
    )
    assert orders[0]["status"] == "CLOSED"
    assert orders[0]["outcome"] == "RETURN_TO_SERVICE"


# ─── A future-dated shop window still protects itself ─────────────────────────

def test_future_shop_window_touching_the_arrival_blocks_assignment(api):
    """PRD §3.4: "If any `OPEN` maintenance order exists for the named vehicle on
    the trip's `service_date` whose closed window from `window_start_min` to
    `window_end_min` intersects the trip's closed interval from
    `scheduled_departure_min` to `scheduled_arrival_min`, the assignment is rejected
    with `ERR_VEHICLE_IN_MAINTENANCE_WINDOW` and HTTP 422."
    PRD §3.3: "A future-dated order behaves quite differently: nothing is displaced,
    the vehicle stays `AVAILABLE`, and the order simply sits there as a booking that
    blocks assignment inside its window, as §3.4 explains."

    Design: Corner/validations/future_maintenance_window_touching_the_arrival_blocks_assignment
    """
    scenario = setup_single_trip_scenario(
        clock="2026-09-01T06:00:00Z", service_date="2026-09-02",
        contract_overrides={"client_name": "Window Touch Hotel"},
        vehicle_overrides={"odometer_km": 500},
        driver_overrides={"full_name": "Window Driver"},
    )
    order = create_maintenance_order(
        scenario["vehicle"]["id"], kind="PREVENTIVE", service_date="2026-09-02",
        window_start_min=468, window_end_min=500,
    )
    assert order["displaced_trip_count"] == 0

    bus = validate_success(api.get_vehicle(scenario["vehicle"]["id"], FLEET))
    assert bus["status"] == "AVAILABLE", "a future-dated order leaves the bus in service"

    response = _assign(
        api, scenario["trip"]["id"], scenario["vehicle"]["id"], scenario["driver"]["id"]
    )
    validate_error(response, ApiErrorId.ERR_VEHICLE_IN_MAINTENANCE_WINDOW.value, 422)

    trip = validate_success(api.get_trip(scenario["trip"]["id"], PLANNER))
    assert trip["dispatch_status"] == "SCHEDULED"
    assert trip.get("vehicle_id") is None


# ─── Livery discipline ────────────────────────────────────────────────────────

def test_branded_bus_cannot_run_another_clients_route(api):
    """PRD §3.4: "The named vehicle's `branding_contract_id` must be null or must
    equal the trip's `contract_id`; a bus wearing one client's livery may not run
    another client's route. A mismatch is rejected with
    `ERR_VEHICLE_BRANDING_MISMATCH` and HTTP 422."

    Design: Corner/validations/branded_vehicle_cannot_serve_another_contracts_trip
    """
    set_clock("2026-09-01T06:00:00Z")
    alpha = create_active_contract(client_name="Alpha Site", site_type="HOTEL")
    beta = create_active_contract(
        client_name="Beta Site", site_type="CAMPUS", ada_min_accessible_pct=0.00
    )
    built = add_single_departure_route(alpha["id"], 420, loop_minutes=48, name="Alpha Loop")
    beta_bus = create_vehicle(
        is_ada_accessible=False, odometer_km=400, branding_contract_id=beta["id"]
    )
    driver = create_driver(full_name="Branding Driver")

    response = _assign(api, built["trip"]["id"], beta_bus["id"], driver["id"])
    validate_error(response, ApiErrorId.ERR_VEHICLE_BRANDING_MISMATCH.value, 422)

    trip = validate_success(api.get_trip(built["trip"]["id"], PLANNER))
    assert trip["dispatch_status"] == "SCHEDULED"
    assert trip.get("vehicle_id") is None

    bus = validate_success(api.get_vehicle(beta_bus["id"], FLEET))
    assert bus["status"] == "AVAILABLE"
    assert bus["committed_block_minutes"] == 0


# ─── Body foreign keys ────────────────────────────────────────────────────────

def test_unknown_body_foreign_keys_return_their_own_not_found(api):
    """PRD §2.6: "Every foreign key supplied in a request body — `contract_id`,
    `route_id`, `vehicle_id`, `driver_id`, `trip_id`, `branding_contract_id`,
    `predecessor_contract_id` — must resolve to an existing row, yielding HTTP 404
    with `ERR_CONTRACT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`,
    or `ERR_TRIP_NOT_FOUND` as appropriate."

    Design: Corner/errors/unknown_body_foreign_keys_return_not_found
    """
    scenario = setup_single_trip_scenario(
        contract_overrides={"client_name": "FK Hotel"},
        vehicle_overrides={"odometer_km": 1_500},
        driver_overrides={"full_name": "FK Driver"},
    )

    missing_vehicle = _assign(
        api, scenario["trip"]["id"], BAD_VEHICLE_ID, scenario["driver"]["id"]
    )
    validate_error(missing_vehicle, ApiErrorId.ERR_VEHICLE_NOT_FOUND.value, 404)

    missing_driver = _assign(
        api, scenario["trip"]["id"], scenario["vehicle"]["id"], BAD_DRIVER_ID
    )
    validate_error(missing_driver, ApiErrorId.ERR_DRIVER_NOT_FOUND.value, 404)

    missing_contract = api.create_credit_memo(
        {
            "contract_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "amount_cents": 1_000,
            "reason": "GOODWILL",
        },
        TEST_USERS["client_liaison_headers"],
    )
    validate_error(missing_contract, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value, 404)

    trip = validate_success(api.get_trip(scenario["trip"]["id"], PLANNER))
    assert trip["dispatch_status"] == "SCHEDULED"
    assert trip.get("vehicle_id") is None
