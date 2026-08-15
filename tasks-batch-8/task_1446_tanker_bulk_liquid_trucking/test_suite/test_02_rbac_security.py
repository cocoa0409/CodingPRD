"""RBAC and authentication-context claims (PRD 2.1, 2.8)."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_customer,
    create_driver,
    create_product,
    create_product_payload,
    create_shipment_payload,
    create_spill_plan_payload,
    make_customer_rep_headers,
    make_driver_headers,
    make_terminal_operator_headers,
    setup_draft_shipment,
    setup_in_transit_shipment,
    setup_loading_shipment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_missing_auth_header_unauthenticated(api):
    """PRD 2.1: "A request missing either header, or carrying a role the system does
    not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_auth_header_unauthenticated
    """
    res = api.list_shipments(headers={})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)


def test_customer_rep_cannot_create_products(api):
    """PRD 2.1: "An authenticated caller whose role is not authorized for the target
    endpoint — or whose entity-backed identity does not match the resource being
    acted on — is rejected with `ERR_INSUFFICIENT_PERMISSIONS`." PRD section 4 limits
    `POST /bulk-liquid/products` to FleetAdmin.

    Design: Corner/rbac/customer_rep_cannot_create_products
    """
    cust = create_customer()
    rep = make_customer_rep_headers(cust["id"])
    res = api.create_product(create_product_payload(), rep)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_terminal_operator_cannot_approve_spill_plan(api):
    """PRD 2.1: "An authenticated caller whose role is not authorized for the target
    endpoint — or whose entity-backed identity does not match the resource being
    acted on — is rejected with `ERR_INSUFFICIENT_PERMISSIONS`." PRD section 4 limits
    `POST /bulk-liquid/spill-response-plans/{planId}/approve` to SafetyOfficer.

    Design: Corner/rbac/terminal_operator_cannot_approve_spill_plan
    """
    cust = create_customer()
    prod = create_product()
    rep = make_customer_rep_headers(cust["id"])
    plan = validate_success(
        api.create_spill_plan(create_spill_plan_payload(cust["id"], prod["id"]), rep), 201)
    validate_success(api.submit_spill_plan(plan["id"], rep), 200)

    res = api.approve_spill_plan(plan["id"], make_terminal_operator_headers("op-x"))
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_driver_cannot_close_meter(api):
    """PRD 2.1: "An authenticated caller whose role is not authorized for the target
    endpoint — or whose entity-backed identity does not match the resource being
    acted on — is rejected with `ERR_INSUFFICIENT_PERMISSIONS`." PRD section 4 limits
    `POST /bulk-liquid/shipments/{shipmentId}/close-meter` to TerminalOperator.

    Design: Corner/rbac/driver_cannot_close_meter
    """
    scenario = setup_loading_shipment()
    res = api.close_meter(
        scenario["ship"]["id"],
        {"meter_start_gal": 0, "meter_end_gal": 1000, "observed_temp_F": 60},
        make_driver_headers(scenario["drv"]["id"]))
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_driver_cannot_start_delivery_of_other(api):
    """PRD 3.5: "the caller's `X-User-ID` must equal the shipment's `driver_id` — any
    other caller, including a different driver, is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/driver_cannot_start_delivery_of_other
    """
    scenario = setup_in_transit_shipment()
    other_driver = create_driver(cdl_number="CDL-2", full_name="Eli Poe")  # not the assigned driver
    res = api.start_delivery(scenario["ship"]["id"], make_driver_headers(other_driver["id"]))
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_customer_rep_cannot_order_for_other_customer(api):
    """PRD 3.3: "a `CustomerRep`, who must set `customer_id` to their own customer id
    or be rejected with `ERR_INSUFFICIENT_PERMISSIONS`".

    Design: Corner/rbac/customer_rep_cannot_order_for_other_customer
    """
    cust_a = create_customer(name="A Co")
    cust_b = create_customer(name="B Co")
    prod = create_product()
    res = api.create_shipment(
        create_shipment_payload(cust_b["id"], prod["id"], ordered_gallons=100, route_miles=10),
        make_customer_rep_headers(cust_a["id"]))
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
