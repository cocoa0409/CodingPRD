"""The fleet: registration, client livery, and the shop."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_maintenance_order,
    assert_vehicle,
    create_active_contract,
    create_maintenance_order,
    create_vehicle,
    set_clock,
    setup_branded_fleet_at_floor,
    setup_maintenance_displacement_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    vehicle_payload,
)

ADMIN = TEST_USERS["contract_admin_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]
PLANNER = TEST_USERS["ops_planner_headers"]


# ─── Registration ─────────────────────────────────────────────────────────────

def test_vehicle_registered_without_livery_carries_no_branding(api):
    """PRD §3.3: "A new vehicle enters the fleet with `status` `AVAILABLE` and
    `committed_block_minutes` at 0."
    PRD §3.3: "The floor is evaluated against the contract named by
    `branding_contract_id`, so stripping a bus of its livery by supplying a null
    value has no contract to test against."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
    increases by exactly one on every mutation."

    Design: Corner/entities/vehicle_branding_contract_id_defaults_to_null
    """
    contract = create_active_contract(client_name="Default Fleet Hotel")

    response = api.create_vehicle(
        vehicle_payload(seat_capacity=24, is_ada_accessible=False, odometer_km=100), FLEET
    )
    vehicle = validate_success(response, expected_status=201)
    assert_vehicle(vehicle)

    assert vehicle.get("branding_contract_id") is None, "an unbranded bus carries no livery"
    assert vehicle["status"] == "AVAILABLE"
    assert vehicle["committed_block_minutes"] == 0
    assert vehicle["version"] == 1

    _, branded_meta = validate_paginated(
        api.list_vehicles(FLEET, params={"branding_contract_id": contract["id"]})
    )
    assert branded_meta["total_count"] == 0, "the bus belongs to no client's branded fleet"

    _, available_meta = validate_paginated(
        api.list_vehicles(FLEET, params={"status": "AVAILABLE"})
    )
    assert available_meta["total_count"] == 1


def test_duplicate_fleet_code_is_rejected(api):
    """PRD §3.3: "If the supplied `fleet_code` is already carried by another vehicle
    row, the registration is rejected with `ERR_FLEET_CODE_DUPLICATE` and HTTP 409."

    Design: Corner/validations/duplicate_fleet_code_is_rejected
    """
    first = validate_success(
        api.create_vehicle(
            vehicle_payload(fleet_code="SHV-3601", seat_capacity=20,
                            is_ada_accessible=False, odometer_km=600),
            FLEET,
        ),
        expected_status=201,
    )

    response = api.create_vehicle(
        vehicle_payload(fleet_code="SHV-3601", seat_capacity=30,
                        is_ada_accessible=True, odometer_km=10, service_interval_km=15_000),
        FLEET,
    )
    validate_error(response, ApiErrorId.ERR_FLEET_CODE_DUPLICATE.value, 409)

    listed, meta = validate_paginated(api.list_vehicles(FLEET))
    assert meta["total_count"] == 1, "the duplicate registration writes no second bus"
    assert listed[0]["id"] == first["id"]


# ─── Client livery ────────────────────────────────────────────────────────────

def test_branding_recomputes_the_contract_fleet_counters(api):
    """PRD §2.7: "`branded_vehicle_count` is the number of vehicle rows whose
    `branding_contract_id` equals the contract's `id` and whose `status` is either
    `AVAILABLE` or `IN_MAINTENANCE`; retired vehicles are excluded.
    `branded_ada_vehicle_count` is the number within that same set whose
    `is_ada_accessible` is true."
    PRD §3.3: "That percentage must be greater than or equal to the contract's
    `ada_min_accessible_pct`; a result exactly equal to the floor passes."

    Design: Corner/entities/branded_fleet_counters_recompute_on_brand
    """
    contract = create_active_contract(
        client_name="ADA Floor Corp", site_type="CORPORATE", ada_min_accessible_pct=50.00
    )
    create_vehicle(is_ada_accessible=True, odometer_km=300, branding_contract_id=contract["id"])
    plain = create_vehicle(is_ada_accessible=False, odometer_km=400)

    branded = validate_success(
        api.brand_vehicle(plain["id"], {"branding_contract_id": contract["id"]}, FLEET)
    )
    assert branded["branding_contract_id"] == contract["id"]

    reread = validate_success(api.get_contract(contract["id"], ADMIN))
    assert reread["branded_vehicle_count"] == 2
    assert reread["branded_ada_vehicle_count"] == 1

    _, meta = validate_paginated(
        api.list_vehicles(FLEET, params={"branding_contract_id": contract["id"]})
    )
    assert meta["total_count"] == 2


def test_branding_below_the_accessibility_floor_is_rejected(api):
    """PRD §3.3: "A wrap that would push the branded ADA share below the floor is
    rejected with `ERR_ADA_FLEET_SHORTFALL` and HTTP 422, and nothing is written."
    PRD §3.3: "it multiplies the contract's resulting `branded_ada_vehicle_count` by
    100, divides by its resulting `branded_vehicle_count`, and rounds half up to two
    decimal places."

    Design: Corner/validations/branding_below_the_ada_floor_is_rejected
    """
    scenario = setup_branded_fleet_at_floor(ada_min_accessible_pct=50.00)
    third = create_vehicle(is_ada_accessible=False, odometer_km=300)

    response = api.brand_vehicle(
        third["id"], {"branding_contract_id": scenario["contract"]["id"]}, FLEET
    )
    validate_error(response, ApiErrorId.ERR_ADA_FLEET_SHORTFALL.value, 422)

    reread_vehicle = validate_success(api.get_vehicle(third["id"], FLEET))
    assert reread_vehicle.get("branding_contract_id") is None, "nothing is written"

    contract = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert contract["branded_vehicle_count"] == 2
    assert contract["branded_ada_vehicle_count"] == 1


# ─── The shop ─────────────────────────────────────────────────────────────────

def test_retiring_a_bus_strips_its_livery(api):
    """PRD §3.3: "With `outcome` `RETIRE`, a vehicle currently `IN_MAINTENANCE`
    moves to `RETIRED` — terminal, permanently out of the fleet — its
    `branding_contract_id` is cleared, and if it had been branded,
    `branded_vehicle_count` and `branded_ada_vehicle_count` are recomputed on the
    contract it was wrapped for; its `version` increments by one."

    Design: Corner/state_machines/maintenance_close_with_retire_strips_branding
    """
    set_clock("2026-09-02T05:00:00Z")
    contract = create_active_contract(client_name="Retire Branding Hotel")
    vehicle = create_vehicle(
        is_ada_accessible=True, odometer_km=900, branding_contract_id=contract["id"]
    )
    order = create_maintenance_order(
        vehicle["id"], kind="CORRECTIVE", service_date="2026-09-02",
        window_start_min=600, window_end_min=720,
    )

    closed = validate_success(
        api.close_maintenance_order(order["id"], {"outcome": "RETIRE"}, FLEET)
    )
    assert closed["outcome"] == "RETIRE"
    assert closed["status"] == "CLOSED"

    reread_vehicle = validate_success(api.get_vehicle(vehicle["id"], FLEET))
    assert reread_vehicle["status"] == "RETIRED"
    assert reread_vehicle.get("branding_contract_id") is None

    reread_contract = validate_success(api.get_contract(contract["id"], ADMIN))
    assert reread_contract["branded_vehicle_count"] == 0
    assert reread_contract["branded_ada_vehicle_count"] == 0

    _, meta = validate_paginated(
        api.list_vehicles(FLEET, params={"branding_contract_id": contract["id"]})
    )
    assert meta["total_count"] == 0


def test_closing_a_closed_shop_order_is_rejected(api):
    """PRD §3.3: "Closing is permitted only while the order's `status` is `OPEN`;
    otherwise the request is rejected with `ERR_MAINTENANCE_ORDER_NOT_OPEN`."
    PRD §3.3: "With `outcome` `RETURN_TO_SERVICE`, a vehicle currently
    `IN_MAINTENANCE` moves back to `AVAILABLE` and its `version` increments by one."

    Design: Corner/state_machines/close_a_closed_maintenance_order_returns_not_open
    """
    set_clock("2026-09-02T05:00:00Z")
    vehicle = create_vehicle(odometer_km=700)
    order = create_maintenance_order(
        vehicle["id"], kind="PREVENTIVE", service_date="2026-09-02",
        window_start_min=600, window_end_min=660,
    )
    validate_success(
        api.close_maintenance_order(order["id"], {"outcome": "RETURN_TO_SERVICE"}, FLEET)
    )

    response = api.close_maintenance_order(order["id"], {"outcome": "RETIRE"}, FLEET)
    validate_error(response, ApiErrorId.ERR_MAINTENANCE_ORDER_NOT_OPEN.value, 409)

    reread_vehicle = validate_success(api.get_vehicle(vehicle["id"], FLEET))
    assert reread_vehicle["status"] == "AVAILABLE", (
        "the refused second close does not retire the bus"
    )

    orders, _ = validate_paginated(api.list_vehicle_maintenance_orders(vehicle["id"], FLEET))
    assert orders[0]["status"] == "CLOSED"
    assert orders[0]["outcome"] == "RETURN_TO_SERVICE"


def test_same_day_shop_order_displaces_the_assigned_trip(api):
    """PRD §3.3: "When the order's `service_date` equals the logical clock's current
    UTC date and the vehicle's `status` is `AVAILABLE`, the vehicle moves
    `AVAILABLE` → `IN_MAINTENANCE` immediately and a four-link displacement cascade
    runs."
    PRD §3.3: "every trip whose `vehicle_id` is this vehicle, whose `service_date`
    equals the order's `service_date`, whose `dispatch_status` is `ASSIGNED`, and
    whose closed interval from `scheduled_departure_min` to `scheduled_arrival_min`
    intersects the closed shop window from `window_start_min` to `window_end_min`,
    is pushed back from `ASSIGNED` to `SCHEDULED` with its `vehicle_id` and
    `driver_id` cleared; the order's `displaced_trip_count` is set to the number of
    trips displaced."
    PRD §3.3: "Beyond those links, `committed_block_minutes` is recomputed on the
    vehicle and `assigned_duty_minutes_current_date` on every driver freed, and the
    vehicle's `version` increments by one."
    PRD §3.3: "The order is created in `status` `OPEN` with `outcome` null,
    `displaced_trip_count` at 0, and `odometer_at_open` set to a snapshot of the
    vehicle's `odometer_km` taken at that moment."

    Design: Difficulty/transitive_cascade/maintenance_open_displaces_trip_and_requeues_request
    """
    scenario = setup_maintenance_displacement_scenario()

    order = validate_success(
        api.create_maintenance_order(
            {
                "vehicle_id": scenario["vehicle"]["id"],
                "kind": "CORRECTIVE",
                "service_date": "2026-09-02",
                "window_start_min": 400,
                "window_end_min": 500,
            },
            FLEET,
        ),
        expected_status=201,
    )
    assert_maintenance_order(order)
    assert order["displaced_trip_count"] == 1
    assert order["status"] == "OPEN"
    assert order["odometer_at_open"] == 30_000

    bus = validate_success(api.get_vehicle(scenario["vehicle"]["id"], FLEET))
    assert bus["status"] == "IN_MAINTENANCE"
    assert bus["committed_block_minutes"] == 0

    trip = validate_success(api.get_trip(scenario["trip"]["id"], PLANNER))
    assert trip["dispatch_status"] == "SCHEDULED"
    assert trip.get("vehicle_id") is None
    assert trip.get("driver_id") is None

    driver = validate_success(api.get_driver(scenario["driver"]["id"], PLANNER))
    assert driver["assigned_duty_minutes_current_date"] == 0


def test_displacement_requeues_the_rider_and_degrades_the_route(api):
    """PRD §3.3: "The fourth link releases riders: for each displaced trip, every
    on-demand request whose `matched_trip_id` named that trip and whose `status` is
    `MATCHED` returns to `PENDING` with `matched_trip_id` cleared and
    `promised_wait_minutes` recomputed."
    PRD §3.3: "if the number of distinct vehicles still bound to that route's trips
    on that `service_date` with `dispatch_status` of `ASSIGNED` or `IN_SERVICE` has
    fallen strictly below the route's `required_vehicle_count`, the route drops to
    `DEGRADED`."
    PRD §3.2: "The **demand requirement** takes the forecast boardings per hour,
    multiplies it by the loop time in minutes, divides that product by the product
    of 60 and the reference seat capacity, and rounds the result up to the next
    whole vehicle."

    Design: Difficulty/transitive_cascade/maintenance_open_displaces_trip_and_requeues_request
    """
    scenario = setup_maintenance_displacement_scenario()
    assert scenario["request"]["status"] == "MATCHED"
    assert scenario["request"]["matched_trip_id"] == scenario["trip"]["id"]

    validate_success(
        api.create_maintenance_order(
            {
                "vehicle_id": scenario["vehicle"]["id"],
                "kind": "CORRECTIVE",
                "service_date": "2026-09-02",
                "window_start_min": 400,
                "window_end_min": 500,
            },
            FLEET,
        ),
        expected_status=201,
    )

    request = validate_success(
        api.get_on_demand_request(scenario["request"]["id"], TEST_USERS["client_liaison_headers"])
    )
    assert request["status"] == "PENDING"
    assert request.get("matched_trip_id") is None
    assert request["promised_wait_minutes"] == 9, (
        "half a 12-minute headway rounded up, plus the three-minute boarding lead"
    )

    route = validate_success(api.get_route(scenario["route"]["id"], PLANNER))
    assert route["status"] == "DEGRADED"
    assert route["required_vehicle_count"] == 8
