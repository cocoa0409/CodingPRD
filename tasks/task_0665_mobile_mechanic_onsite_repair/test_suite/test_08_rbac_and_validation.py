"""Role-based access control, ownership, authentication, and a body-validation error.

Translates the corner `rbac` instances and the corner `errors` part-line invalid-quantity
instance.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, build_user_headers,
    make_customer_headers, make_mechanic_headers,
    set_clock, create_customer, create_mechanic, create_service_request,
    create_catalog_part, send_quote, approve_quote,
    setup_quoted_request, setup_approved_request, setup_in_progress_request,
    create_quote_payload, create_dispatch_payload, create_approve_quote_payload,
    create_part_line_payload, _sr_version,
)
from test_helpers.test_users import TEST_USERS

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_dispatcher_cannot_send_quote(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/dispatcher_cannot_send_quote
    """
    set_clock()
    customer = create_customer(home_zone_code="Z1", email="c21@x.com")
    sr = create_service_request(customer["id"], vehicle_vin="1HGCM82633A100022")
    res = api.send_quote(sr["id"], create_quote_payload(estimated_labor_hours=1.0,
                                                        estimated_parts_cents=0,
                                                        labor_rate_cents_per_hour=9000),
                         DISPATCHER)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_customer_cannot_dispatch(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/customer_cannot_dispatch
    """
    ctx = setup_approved_request(email="c22@x.com")
    sr, mechanic, customer = ctx["service_request"], ctx["mechanic"], ctx["customer"]
    version = _sr_version(sr["id"])
    res = api.dispatch(sr["id"], create_dispatch_payload(mechanic["id"], version,
                                                         routing_mode="ON_SITE"),
                       make_customer_headers(customer["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "APPROVED"


def test_customer_cannot_approve_other_customers_quote(api):
    """PRD §2.1: "When an entity-backed user (a `Customer`, `Mechanic`, or
    `FleetManager`) targets a resource that they do not own, the request is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Concretely, a `Customer` may act only on their
    own `ServiceRequest` records and their descendants".

    Design: Corner/rbac/customer_cannot_approve_other_customers_quote
    """
    ctx = setup_quoted_request(email="c23@x.com")  # owner
    owner, quote, sr = ctx["customer"], ctx["quote"], ctx["service_request"]
    impostor = create_customer(home_zone_code="Z1", email="c24@x.com",
                               full_name="C TwentyFour")

    version = _sr_version(sr["id"])
    res = api.approve_quote(quote["id"], create_approve_quote_payload(version),
                            make_customer_headers(impostor["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "QUOTED"


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Both headers must be present and well-formed on every request ... A
    request missing or malformed in either header is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    set_clock()
    customer = create_customer(home_zone_code="Z1", email="c25@x.com")
    sr = create_service_request(customer["id"], vehicle_vin="1HGCM82633A100025")
    res = api.get_service_request(sr["id"], headers={"Content-Type": "application/json"})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_part_line_invalid_quantity_zero(api):
    """PRD §3.6: "A mechanic sources parts for a request by naming a `catalog_part_id`
    and a `quantity` that must be strictly greater than zero."
    PRD §2.10: "and only then the structural validity of the request body
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/errors/dispatch_part_line_invalid_quantity_zero
    """
    part = create_catalog_part(wholesale_cost_cents=100, sku="QZ1", name="Bolt")
    ctx = setup_in_progress_request(mechanic_rate=9000, email="c19@x.com")
    res = api.source_part_line(ctx["service_request"]["id"],
                               create_part_line_payload(part["id"], quantity=0),
                               make_mechanic_headers(ctx["mechanic"]["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
