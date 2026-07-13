"""Vehicle inventory CRUD, defaults, uniqueness, and fuel-log odometer reconciliation."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    create_vehicle_payload, create_fuel_log_payload, assert_vehicle,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
TECH = TEST_USERS["shop_tech_headers"]


def test_create_vehicle_returns_201_with_defaults(api):
    """PRD §3.1: "A new vehicle starts as a POOL asset with assignment_type POOL,
    operational_status IN_SERVICE, lifecycle_status ACTIVE, an odometer_miles of 0,
    and derived counters — lifetime_maintenance_cents, lifetime_fuel_cents,
    open_accident_count, and replacement_score — all at 0, with cost_per_mile_cents
    null until the odometer leaves zero."
    PRD §2.4: "a version (an integer that starts at 1 and increments by 1 on every
    mutation to the resource)."

    Design: Corner/entities/create_vehicle_returns_201_defaults
    """
    res = api.create_vehicle(
        create_vehicle_payload(vin="VIN-NEW-1", vehicle_class="SUV",
                               acquisition_cost_cents=3000000,
                               in_service_date="2024-05-01T00:00:00Z"),
        ADMIN)
    vehicle = validate_success(res, 201)
    assert_vehicle(vehicle)
    assert vehicle["operational_status"] == "IN_SERVICE"
    assert vehicle["lifecycle_status"] == "ACTIVE"
    assert vehicle["assignment_type"] == "POOL"
    assert vehicle["odometer_miles"] == 0
    assert vehicle["version"] == 1


def test_create_vehicle_missing_vin_returns_validation(api):
    """PRD §2.8: "body well-formedness — required fields present, enums in range, numbers
    within their stated constraints such as requested_end strictly after requested_start
    and third_party_liable_pct within 0 to 1 inclusive (ERR_VALIDATION, HTTP 422)".
    PRD §3.1: "A FleetAdmin registers a vehicle by supplying its vin (unique across the
    fleet, 1 to 64 characters)".

    Design: Corner/entities/create_vehicle_missing_vin_returns_validation
    """
    payload = create_vehicle_payload(vehicle_class="SUV", acquisition_cost_cents=3000000,
                                     in_service_date="2024-05-01T00:00:00Z")
    del payload["vin"]
    res = api.create_vehicle(payload, ADMIN)
    validate_error(res, "ERR_VALIDATION")


def test_get_vehicle_unknown_id_returns_not_found(api):
    """PRD §2.8: "the first identifier that does not resolve to an existing resource
    yields ERR_NOT_FOUND. This applies uniformly to reads, creates, and transitions."

    Design: Corner/entities/get_vehicle_unknown_id_returns_not_found
    """
    res = api.get_vehicle(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_list_vehicles_bad_limit_returns_pagination_invalid(api):
    """PRD §2.3: "A limit outside the inclusive range of 1 to 100, or a negative
    offset, is rejected with ERR_PAGINATION_INVALID."

    Design: Corner/entities/list_vehicles_bad_limit_returns_pagination_invalid
    """
    res = api.list_vehicles(ADMIN, params={"limit": 0})
    validate_error(res, "ERR_PAGINATION_INVALID")


def test_duplicate_vin_returns_duplicate(api):
    """PRD §3.1: "A duplicate vin is rejected with ERR_DUPLICATE."

    Design: Corner/entities/duplicate_vin_returns_duplicate
    """
    validate_success(api.create_vehicle(
        create_vehicle_payload(vin="VIN-DUP", vehicle_class="SEDAN",
                               acquisition_cost_cents=2000000,
                               in_service_date="2024-01-01T00:00:00Z"), ADMIN), 201)
    res = api.create_vehicle(
        create_vehicle_payload(vin="VIN-DUP", vehicle_class="VAN",
                               acquisition_cost_cents=2500000,
                               in_service_date="2024-02-01T00:00:00Z"), ADMIN)
    validate_error(res, "ERR_DUPLICATE")


def test_assign_department_without_id_returns_assignment_invalid(api):
    """PRD §3.1: "A DEPARTMENT_ASSIGNED assignment must name a department, and a POOL
    assignment must not carry an assigned department; either shape violation is rejected
    with ERR_ASSIGNMENT_INVALID."

    Design: Corner/validations/assign_department_without_id_returns_assignment_invalid
    """
    vehicle = validate_success(api.create_vehicle(
        create_vehicle_payload(vin="VIN-ASG-1"), ADMIN), 201)
    res = api.assign_vehicle(vehicle["id"], {"assignment_type": "DEPARTMENT_ASSIGNED"}, ADMIN)
    validate_error(res, "ERR_ASSIGNMENT_INVALID")


def test_fuel_log_advances_vehicle_odometer_and_fuel(api):
    """PRD §3.4: "Posting a reading advances the vehicle's odometer_miles to the larger
    of its current value and the reading's odometer, adds the reading's fuel_cost_cents
    to the vehicle's lifetime_fuel_cents, and recomputes cost_per_mile_cents."

    Design: Corner/entities/fuel_log_advances_vehicle_odometer
    """
    vehicle = validate_success(api.create_vehicle(
        create_vehicle_payload(vin="VIN-ODO"), ADMIN), 201)
    validate_success(api.create_fuel_log(
        vehicle["id"],
        create_fuel_log_payload(reading_at="2026-03-02T00:00:00Z", gallons=12,
                                fuel_cost_cents=4500, odometer_miles=1200, idle_minutes=10),
        TECH), 201)
    updated = validate_success(api.get_vehicle(vehicle["id"], ADMIN), 200)
    assert updated["odometer_miles"] == 1200
    assert updated["lifetime_fuel_cents"] == 4500
