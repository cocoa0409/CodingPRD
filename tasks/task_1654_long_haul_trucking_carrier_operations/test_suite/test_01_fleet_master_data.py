"""Fleet master data: driver registration defaults and pay-config rules,
tractor registration and the out-of-service guard cycle (PRD §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_driver,
    assert_tractor,
    create_driver,
    create_driver_payload,
    create_tractor,
    create_tractor_payload,
    make_fleet_admin_headers,
    set_clock,
    setup_planned_trip,
    validate_error,
    validate_success,
)

FLEET_ADMIN = make_fleet_admin_headers()
DISPATCHER_VIEW = {"X-User-ID": "dispatcher-1", "X-User-Role": "Dispatcher"}


def test_driver_create_applies_server_defaults(api):
    """PRD §3.1: "A new driver starts with `employment_status` `ACTIVE`,
    `duty_status` `OFF_DUTY` until the first duty event says otherwise, a
    `safety_score` of 100, and `version` 1."

    Design: Corner/entities/driver_create_applies_defaults
    """
    set_clock("2026-08-01T06:00:00Z")
    data = validate_success(api_client.create_driver(
        create_driver_payload(cdl_number="CDL-C1", full_name="C One"),
        FLEET_ADMIN), expected_status=201)
    assert_driver(data)
    assert data["employment_status"] == "ACTIVE"
    assert data["duty_status"] == "OFF_DUTY"
    assert data["safety_score"] == 100
    assert data["version"] == 1


def test_driver_create_missing_cdl_number_rejected(api):
    """PRD §2.9: "Required fields must be present, enum values must belong to
    their declared sets, numeric minimums must hold (positive rates, weights,
    gallon counts; non-negative odometers and deadhead plans), documented
    datetime orderings must hold (a load's delivery appointment strictly after
    its pickup appointment; a settlement's `period_end` strictly after its
    `period_start`), and no client-supplied event timestamp may fall after the
    logical now — failures are `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/driver_create_missing_required_returns_invalid_request
    """
    payload = create_driver_payload(full_name="No Cdl")
    del payload["cdl_number"]
    resp = api_client.create_driver(payload, FLEET_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_driver_create_invalid_pay_model_rejected(api):
    """PRD §3.1: "`pay_model` is either `MILEAGE` or `PERCENTAGE`, and it must
    be complete for its kind."
    PRD §2.9: "Required fields must be present, enum values must belong to
    their declared sets ... — failures are `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/driver_create_invalid_pay_model_enum_returns_invalid_request
    """
    resp = api_client.create_driver(
        create_driver_payload(cdl_number="CDL-C3", pay_model="WEEKLY"),
        FLEET_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_driver_percentage_model_requires_percentage_bp(api):
    """PRD §3.1: "A `MILEAGE` driver requires a `pay_rate_cents_per_mile` of at
    least 1; a `PERCENTAGE` driver requires a `pay_percentage_bp` share of no
    less than 1 and no more than 10000 basis points. Registering a driver whose
    pay configuration does not match its model is rejected with
    `ERR_PAY_CONFIG_INCOMPLETE` (HTTP 422)."

    Design: Corner/entities/driver_percentage_model_requires_percentage_bp
    """
    payload = create_driver_payload(cdl_number="CDL-C4", pay_model="PERCENTAGE")
    del payload["pay_rate_cents_per_mile"]
    resp = api_client.create_driver(payload, FLEET_ADMIN)
    validate_error(resp, ApiErrorId.ERR_PAY_CONFIG_INCOMPLETE)


def test_driver_create_ignores_client_supplied_safety_score(api):
    """PRD §3.1: "A new driver starts with `employment_status` `ACTIVE`,
    `duty_status` `OFF_DUTY` until the first duty event says otherwise, a
    `safety_score` of 100, and `version` 1."
    PRD §2.5: "Every primary resource — Driver, Tractor, CustomerAccount, Lane,
    StateFuelRate, Load, Trip, AccessorialCharge, FuelPurchase, SafetyEvent,
    Settlement, and Invoice — carries a standard set of system-managed fields".

    Design: Corner/entities/driver_create_computed_input_ignored
    """
    data = validate_success(api_client.create_driver(
        create_driver_payload(cdl_number="CDL-C5", safety_score=5),
        FLEET_ADMIN), expected_status=201)
    assert data["safety_score"] == 100, (
        "client-supplied safety_score must not override the server default")


def test_get_driver_unknown_id_returns_not_found(api):
    """PRD §2.10: "Each resource type has its own not-found error:
    `ERR_DRIVER_NOT_FOUND`, `ERR_TRACTOR_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_LANE_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`,
    `ERR_ACCESSORIAL_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`, `ERR_FUEL_RATE_NOT_FOUND`, and
    `ERR_SAFETY_EVENT_NOT_FOUND` (all HTTP 404)."

    Design: Corner/entities/driver_not_found_returns_404
    """
    resp = api_client.get_driver(NON_EXISTENT_UUID, DISPATCHER_VIEW)
    validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_FOUND)


def test_tractor_create_get_roundtrip(api):
    """PRD §3.1: "A registered tractor begins `AVAILABLE`. From `AVAILABLE` —
    and only from `AVAILABLE`, otherwise `ERR_TRACTOR_NOT_AVAILABLE` — a
    `FleetAdmin` may park a unit as `OUT_OF_SERVICE`".
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/entities/tractor_create_get_roundtrip
    """
    created = create_tractor(unit_number="T-C1")
    assert_tractor(created)
    fetched = validate_success(
        api_client.get_tractor(created["id"], DISPATCHER_VIEW))
    assert_tractor(fetched)
    assert fetched["unit_number"] == "T-C1"
    assert fetched["status"] == "AVAILABLE"
    assert fetched["odometer_miles"] == 100000
    assert fetched["current_fuel_gallons"] == 150


def test_tractor_create_ignores_client_supplied_system_fields(api):
    """PRD §2.5: "`id` — a server-minted UUID with no type prefix, unique
    across the resource type."
    PRD §2.5: "`version` — an integer assigned the value 1 at creation and
    incremented by one on every mutation of the resource, again including
    cascaded mutations."

    Design: Corner/entities/tractor_create_system_fields_input_ignored
    """
    forged_id = "11111111-2222-4333-8444-555555555555"
    data = validate_success(api_client.create_tractor(
        create_tractor_payload(unit_number="T-C2", id=forged_id, version=9),
        FLEET_ADMIN), expected_status=201)
    assert data["id"] != forged_id, "server must mint the id, not honor the client's"
    assert data["version"] == 1


def test_tractor_out_of_service_guarded_cycle(api):
    """PRD §3.1: "From `AVAILABLE` — and only from `AVAILABLE`, otherwise
    `ERR_TRACTOR_NOT_AVAILABLE` — a `FleetAdmin` may park a unit as
    `OUT_OF_SERVICE`, and a unit in `OUT_OF_SERVICE` may be returned to
    `AVAILABLE` (any other source state draws
    `ERR_TRACTOR_NOT_OUT_OF_SERVICE`)."

    Design: Corner/state_machines/tractor_out_of_service_guarded_cycle
    """
    ctx = setup_planned_trip(cdl_number="CDL-C22", unit_number="T-C22B")
    assigned_tractor = ctx["tractor"]
    free = create_tractor(unit_number="T-C22A")

    parked = validate_success(
        api_client.out_of_service_tractor(free["id"], FLEET_ADMIN))
    assert parked["status"] == "OUT_OF_SERVICE"
    validate_error(api_client.out_of_service_tractor(free["id"], FLEET_ADMIN),
                   ApiErrorId.ERR_TRACTOR_NOT_AVAILABLE)
    returned = validate_success(
        api_client.return_to_service_tractor(free["id"], FLEET_ADMIN))
    assert returned["status"] == "AVAILABLE"
    validate_error(api_client.return_to_service_tractor(free["id"], FLEET_ADMIN),
                   ApiErrorId.ERR_TRACTOR_NOT_OUT_OF_SERVICE)
    validate_error(
        api_client.out_of_service_tractor(assigned_tractor["id"], FLEET_ADMIN),
        ApiErrorId.ERR_TRACTOR_NOT_AVAILABLE)
