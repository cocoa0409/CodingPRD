"""Onboarding, order creation/retrieval, uniqueness, and role-based access.

Translated from SCAFFOLD_CORNER_DESIGN.yaml §1.9 (entities + rbac sections).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_shipment_order,
    attach_vehicle,
    create_order_payload,
    make_shipper_headers,
    register_carrier,
    register_shipper,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_order_returns_201_with_draft_and_default_enums(api):
    """PRD §3.2: "A Shipper opens a shipment by creating an order, which is born
    in DRAFT status with its shipper_id set from X-User-ID and its version at 1."
    PRD §3.2: "Two enum options carry defaults: delivery_mode is DOOR_TO_DOOR or
    TERMINAL and defaults to DOOR_TO_DOOR, and service_level is STANDARD or
    EXPEDITED and defaults to STANDARD."

    Design: Corner/entities/create_shipment_order_returns_201_with_system_fields
    """
    shipper = register_shipper()
    payload = create_order_payload(route_miles=1200, transport_type="OPEN")
    resp = api.create_order(payload, make_shipper_headers(shipper["id"]))
    data = validate_success(resp, expected_status=201)
    assert_shipment_order(data)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["delivery_mode"] == "DOOR_TO_DOOR"
    assert data["service_level"] == "STANDARD"


def test_get_order_unknown_id_returns_not_found(api):
    """PRD §2.9: "the system validates each identifier left to right and rejects
    the request with ERR_NOT_FOUND at the first identifier that does not resolve
    to an existing resource."

    Design: Corner/entities/get_order_not_found_returns_404
    """
    resp = api.get_order(NON_EXISTENT_UUID, TEST_USERS["broker_headers"])
    validate_error(resp, "ERR_NOT_FOUND", expected_status=404)


def test_create_order_missing_route_miles_is_invalid_request(api):
    """PRD §3.2: "the quoted route distance route_miles (which must be greater
    than 0)".
    PRD §3.2: "A malformed body — a non-positive route_miles, a window whose end
    is at or before its start, an invalid enum member — is rejected with
    ERR_INVALID_REQUEST."

    Design: Corner/entities/create_order_missing_route_miles_returns_invalid_request
    """
    shipper = register_shipper()
    payload = {
        "origin_zip": "90001",
        "dest_zip": "10001",
        "transport_type": "OPEN",
        "pickup_window_start": "2026-06-01T08:00:00Z",
        "pickup_window_end": "2026-06-05T18:00:00Z",
    }
    resp = api.create_order(payload, make_shipper_headers(shipper["id"]))
    validate_error(resp, "ERR_INVALID_REQUEST", expected_status=422)


def test_duplicate_mc_number_rejected(api):
    """PRD §3.1: "The mc_number must be unique across carriers; a duplicate is
    rejected with ERR_DUPLICATE_MC_NUMBER."

    Design: Corner/entities/carrier_duplicate_mc_number_returns_409
    """
    register_carrier(mc_number="MC-DUP-001", legal_name="First Co")
    resp = api.create_carrier(
        {
            "legal_name": "Second Co",
            "mc_number": "MC-DUP-001",
            "cargo_insurance_limit_cents": 2_000_000,
            "insurance_expiry_date": "2027-01-01T00:00:00Z",
            "equipment_type": "ENCLOSED",
        },
        TEST_USERS["broker_headers"],
    )
    validate_error(resp, "ERR_DUPLICATE_MC_NUMBER", expected_status=409)


def test_duplicate_shipper_email_rejected(api):
    """PRD §3.1: "The email must be unique across shippers; a duplicate
    registration is rejected with ERR_DUPLICATE_EMAIL."

    Design: Corner/entities/shipper_duplicate_email_returns_409
    """
    register_shipper(email="dup-onboard@x.com", full_name="Dup A")
    resp = api.create_shipper(
        {"email": "dup-onboard@x.com", "full_name": "Dup B"}, TEST_USERS["admin_headers"]
    )
    validate_error(resp, "ERR_DUPLICATE_EMAIL", expected_status=409)


def test_list_vehicles_filtered_by_order_returns_the_orders_vehicles(api):
    """PRD §4 endpoint table: "List vehicles (filter order_id)".
    PRD §3.2: "A Vehicle belongs to its order via order_id".
    PRD §2.3: "Unless otherwise specified, all list endpoints return resources
    sorted by their creation timestamp (created_at) in ascending order."

    Design: Corner/entities/list_vehicles_by_order_returns_array
    """
    shipper = register_shipper()
    resp = api.create_order(
        create_order_payload(route_miles=1200, transport_type="OPEN"),
        make_shipper_headers(shipper["id"]),
    )
    order = validate_success(resp, expected_status=201)
    attach_vehicle(order["id"], shipper["id"], make="Honda", model="Civic")
    attach_vehicle(order["id"], shipper["id"], make="Toyota", model="Camry")

    list_resp = api.list_vehicles(
        make_shipper_headers(shipper["id"]), params={"order_id": order["id"]}
    )
    data, _meta = validate_paginated(list_resp)
    assert len(data) == 2, f"Expected 2 vehicles for the order, got {len(data)}"
    assert all(v["order_id"] == order["id"] for v in data)


# ─── Role-based access control ─────────────────────────────────────────────

def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing, the request is rejected with
    ERR_MISSING_AUTH."

    Design: Corner/rbac/missing_auth_header_returns_missing_auth
    """
    resp = api.get_order(NON_EXISTENT_UUID, TEST_USERS["anonymous_headers"])
    validate_error(resp, "ERR_MISSING_AUTH", expected_status=401)


def test_carrier_cannot_create_order_forbidden(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/carrier_cannot_create_order_returns_forbidden
    """
    carrier = register_carrier()
    from test_helpers import make_carrier_headers

    resp = api.create_order(
        create_order_payload(route_miles=1200, transport_type="OPEN"),
        make_carrier_headers(carrier["id"]),
    )
    validate_error(resp, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_shipper_cannot_suspend_carrier_forbidden(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."
    PRD §4 endpoint table: "Suspend a carrier | Admin".

    Design: Corner/rbac/shipper_cannot_suspend_carrier_returns_forbidden
    """
    shipper = register_shipper()
    carrier = register_carrier()
    resp = api.suspend_carrier(carrier["id"], make_shipper_headers(shipper["id"]))
    validate_error(resp, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_shipper_cannot_cancel_another_shippers_order(api):
    """PRD §2.1: "A shipper acting on an order it does not own is rejected with
    ERR_NOT_ORDER_OWNER."

    Design: Corner/rbac/shipper_cannot_cancel_other_shippers_order_returns_not_order_owner
    """
    owner = register_shipper(email="owner-x@x.com")
    other = register_shipper(email="other-x@x.com")
    order = validate_success(
        api.create_order(
            create_order_payload(route_miles=1200, transport_type="OPEN"),
            make_shipper_headers(owner["id"]),
        ),
        expected_status=201,
    )
    resp = api.cancel_order(order["id"], make_shipper_headers(other["id"]))
    validate_error(resp, "ERR_NOT_ORDER_OWNER", expected_status=403)
