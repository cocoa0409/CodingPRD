"""Resource creation basics, computed/default fields, not-found, and RBAC denials.

Queue B: entities (customer common fields, customer 404, order missing field, order fuel_type
computed, vehicle default fuel level) and rbac (driver denied POST /routes, missing headers).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    assert_customer, assert_vehicle,
    make_member_headers,
    post_fuel_price, new_customer, new_truck,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
DRIVER = TEST_USERS["driver_headers"]


# ─── Queue B: entities ──────────────────────────────────────────────────────

def test_create_customer_returns_active_with_version_one(api):
    """PRD §3.1: "A customer's `status` is set to `ACTIVE` at registration and is the only
    lifecycle value it ever holds."
    PRD §2.4: "an integer `version` that starts at 1 on creation and increases by exactly 1
    on every mutation of that resource."

    Design: Corner/entities/create_customer_returns_common_fields
    """
    res = api.create_customer(
        {"name": "Nora", "email": "nora@x.com", "customer_type": "INDIVIDUAL"}, ADMIN)
    customer = validate_success(res, 201)
    assert_customer(customer)
    assert customer["status"] == "ACTIVE"
    assert customer["version"] == 1


def test_get_customer_unknown_id_not_found(api):
    """PRD §2.8: "the first unknown identifier determines the error: a missing customer
    yields `ERR_CUSTOMER_NOT_FOUND`,"

    Design: Corner/entities/get_customer_not_found
    """
    res = api.get_customer(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_CUSTOMER_NOT_FOUND", expected_status=404)


def test_create_order_missing_requested_gallons_rejected(api):
    """PRD §2.8: "A malformed body, a missing required field, or a value outside a field's
    allowed enum or type is a request-shape failure reported as `ERR_VALIDATION` (HTTP
    400)."

    Design: Corner/entities/create_order_missing_required_field_rejected
    """
    post_fuel_price()
    cust = new_customer(name="Otto", email="otto@x.com")
    veh = get_success_data(api.create_vehicle(
        {"customer_id": cust["id"], "make_model": "Up", "fuel_type": "REGULAR",
         "tank_capacity_gallons": 40}, make_member_headers(cust["id"])))
    res = api.create_order(
        {"customer_id": cust["id"], "vehicle_id": veh["id"], "zone": "ZONE_A",
         "delivery_address": "no gallons",
         "delivery_window_start": "2026-05-02T09:00:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_member_headers(cust["id"]))
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_order_fuel_type_copied_from_vehicle(api):
    """PRD §3.4: "The order's `fuel_type` is not supplied by the caller; it is copied from
    the vehicle's required grade at creation."

    Design: Corner/entities/order_fuel_type_copied_from_vehicle_computed
    """
    post_fuel_price(fuel_type="DIESEL", price_per_gallon_cents=459)
    cust = new_customer(name="Pat", email="pat@x.com")
    veh = get_success_data(api.create_vehicle(
        {"customer_id": cust["id"], "make_model": "Ram", "fuel_type": "DIESEL",
         "tank_capacity_gallons": 100, "current_fuel_level_gallons": 0},
        make_member_headers(cust["id"])))
    res = api.create_order(
        {"customer_id": cust["id"], "vehicle_id": veh["id"], "zone": "ZONE_A",
         "delivery_address": "Diesel Ln", "requested_gallons": 10,
         "delivery_window_start": "2026-05-02T09:00:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_member_headers(cust["id"]))
    order = validate_success(res, 201)
    assert order["fuel_type"] == "DIESEL", "order fuel_type mirrors the DIESEL vehicle"


def test_vehicle_default_fuel_level_zero(api):
    """PRD §3.2: "Optional inputs include `fleet_account_id` (which links the vehicle to a
    fleet account; it is null for a standalone individual vehicle), a starting
    `current_fuel_level_gallons` (defaulting to 0), and a `monthly_spend_cap_cents`
    per-vehicle spend ceiling (defaulting to 0, which means unlimited)."

    Design: Corner/entities/vehicle_default_fuel_level_zero
    """
    cust = new_customer(name="Quin", email="quin@x.com")
    res = api.create_vehicle(
        {"customer_id": cust["id"], "make_model": "Polo", "fuel_type": "REGULAR",
         "tank_capacity_gallons": 40},
        make_member_headers(cust["id"]))
    vehicle = validate_success(res, 201)
    assert_vehicle(vehicle)
    assert vehicle["current_fuel_level_gallons"] == 0
    assert vehicle["status"] == "ACTIVE"


# ─── Queue B: rbac ──────────────────────────────────────────────────────────

def test_driver_cannot_create_route(api):
    """PRD §2.1: "When the headers are present and valid but the declared role is not
    permitted to perform the requested operation — or an ownership-scoped role attempts to
    act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/driver_cannot_create_route
    """
    truck = new_truck(plate="TRK-RB")
    res = api.create_route(
        {"truck_id": truck["id"], "assigned_driver_id": "driver-1", "zone": "ZONE_A",
         "window_start": "2026-05-02T06:00:00Z", "window_end": "2026-05-02T20:00:00Z"},
        DRIVER)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request to the API must be authenticated with two mandatory HTTP
    headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which
    declares the operational capacity under which the request is made. When either header is
    missing or malformed, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    res = api.create_customer(
        {"name": "NoAuth", "email": "noauth@x.com", "customer_type": "INDIVIDUAL"}, {})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=401)
