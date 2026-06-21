"""Entity CRUD corner tests (queue B): creation, required/typed fields,
defaults, not-found, computed fields, FK reverse-reachability. PRD §3.1, §2.7,
§2.8, §2.9, §3.10.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    get_success_data,
    setup_settlement_open,
    validate_error,
    validate_paginated,
    validate_success,
)

FM = TEST_USERS["fleet_manager_headers"]
TG = TEST_USERS["telematics_gateway_headers"]


# ---- entities -------------------------------------------------------------

def test_create_vehicle_returns_system_fields(api):
    """PRD §3.1: "A new vehicle starts with `status` `AVAILABLE`,
    `odometer_miles` of 0, and `open_block_count` of 0."
    PRD §2.4: "an integer `version` that starts at 1 and increments by 1 on
    every mutation of that resource."

    Design: Corner/entities/create_vehicle_returns_201_with_system_fields
    """
    data = validate_success(
        api.create_vehicle({"vin": "VINNEW0001", "class": "LIGHT_DUTY"}, FM), 201)
    assert data["status"] == "AVAILABLE", data
    assert data["odometer_miles"] == 0, data
    assert data["open_block_count"] == 0, data
    assert data["version"] == 1, data


def test_create_lease_missing_required_field(api):
    """PRD §2.7: "After those come well-formedness of the request body
    (required fields present and correctly typed, enum values within their
    allowed sets)."
    PRD §3.2: "`overage_model` (either `CONTRACT_FLAT` or `TIERED_EXCESS`)" is
    a required commercial term.

    Omitting overage_model yields ERR_INVALID_REQUEST.

    Design: Corner/entities/create_lease_missing_required_field_returns_invalid_request
    """
    lessee = get_success_data(api.create_lessee(
        {"company_name": "RF Co", "billing_email": "rf@x.com"}, FM))
    vehicle = get_success_data(api.create_vehicle(
        {"vin": "VINRF00001", "class": "LIGHT_DUTY"}, FM))
    resp = api.create_lease(
        {"lessee_id": lessee["id"], "vehicle_id": vehicle["id"],
         "term_start": "2026-01-01T00:00:00Z", "term_end": "2026-12-31T00:00:00Z",
         "contracted_miles": 60000, "per_mile_overage_cents": 25,
         "collision_deductible_cents": 100000, "waterfall_model": "DEDUCTIBLE_FIRST"}, FM)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_create_vehicle_invalid_enum_class(api):
    """PRD §3.1: "where `class` is one of `LIGHT_DUTY`, `MEDIUM_DUTY`, or
    `HEAVY_DUTY` and determines IFTA qualification."
    PRD §2.7: "enum values within their allowed sets."

    class='SPACESHIP' is outside the allowed set → ERR_INVALID_REQUEST.

    Design: Corner/entities/create_vehicle_invalid_enum_class_returns_invalid_request
    """
    resp = api.create_vehicle({"vin": "VINENUM001", "class": "SPACESHIP"}, FM)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_driver_default_license_status_valid(api):
    """PRD §3.1: "A driver begins with `license_status` `VALID`, and a fleet
    operator may later mark a license `SUSPENDED`."

    Design: Corner/entities/driver_default_license_status_valid_on_create
    """
    lessee = get_success_data(api.create_lessee(
        {"company_name": "DD Co", "billing_email": "dd@x.com"}, FM))
    data = validate_success(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "Defaulted",
         "license_number": "LIC-DD-1"}, FM), 201)
    assert data["license_status"] == "VALID", data


def test_vehicle_get_nonexistent_returns_not_found(api):
    """PRD §2.7: "then existence of every path-referenced and
    foreign-key-referenced resource, validated left to right."

    A GET on a non-existent vehicle id yields ERR_NOT_FOUND.

    Design: Corner/entities/vehicle_get_nonexistent_returns_not_found
    """
    resp = api.get_vehicle(NON_EXISTENT_UUID, FM)
    validate_error(resp, "ERR_NOT_FOUND")


def test_lessee_outstanding_balance_after_settlement(api):
    """PRD §3.10: "Two events add to it: finalizing an overage settlement adds
    that settlement's `net_charge_cents`, and settling a total-loss repair
    adds that repair order's `lessee_responsible_cents`."

    CONTRACT_FLAT settlement with net 625000 → lessee balance 625000.

    Design: Corner/entities/lessee_outstanding_balance_reconciled_after_settlement
    """
    lessee, vehicle, lease, settlement = setup_settlement_open(
        driven_odometer=85000, overage_model="CONTRACT_FLAT",
        contracted_miles=60000, per_mile_overage_cents=25, harsh_events=10,
        idle_minutes=100,
    )
    validate_success(api.finalize_settlement(settlement["id"], FM), 200)
    data = validate_success(api.get_lessee(lessee["id"], FM), 200)
    assert data["outstanding_balance_cents"] == 625000, data


# ---- FK reverse-reachability ----------------------------------------------

def test_fk_reverse_telematics_by_vehicle(api):
    """PRD §2.9: "A handful of list endpoints are reached through a parent
    path segment — the telematics readings and maintenance orders of a given
    vehicle."

    GET /fleet/vehicles/{id}/telematics-readings returns the vehicle's
    readings.

    Design: Corner/entities/fk_reverse_telematics_by_vehicle_subresource
    """
    vehicle = get_success_data(api.create_vehicle(
        {"vin": "VINFK00001", "class": "HEAVY_DUTY"}, FM))
    get_success_data(api.create_telematics_reading(
        {"vehicle_id": vehicle["id"], "jurisdiction": "CA", "odometer_miles": 1000,
         "segment_miles": 1000, "recorded_at": "2026-06-01T00:00:00Z"}, TG))
    resp = api.list_vehicle_telematics(vehicle["id"], FM)
    data, meta = validate_paginated(resp)
    assert meta.get("total_count") == 1, meta


def test_fk_reverse_repair_orders_by_lease(api):
    """PRD §2.9: "Other lists are flat collections filterable by a
    foreign-key query parameter."

    GET /fleet/repair-orders?lease_id=... returns the lease's repair orders.

    Design: Corner/entities/fk_reverse_repair_orders_by_lease_filtered_list
    """
    from test_helpers import read_vehicle, setup_active_lease
    lessee, vehicle, lease = setup_active_lease(vehicle_class="MEDIUM_DUTY")
    veh = read_vehicle(vehicle["id"])
    get_success_data(api.create_repair_order(
        {"vehicle_id": vehicle["id"], "lease_id": lease["id"],
         "expected_vehicle_version": veh["version"]}, FM))
    resp = api.list_repair_orders(FM, params={"lease_id": lease["id"]})
    data, meta = validate_paginated(resp)
    assert meta.get("total_count") == 1, meta
