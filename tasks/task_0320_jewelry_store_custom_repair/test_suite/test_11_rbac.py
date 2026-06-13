"""Corner breadth tests — rbac section: role-exclusive operations, an allowed shared
Customer write, and the missing-auth gate.

Translates queue-B corner instances under section `rbac`.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_customer,
    create_inventory_item,
    drive_repair_ticket_to_qc_no_parts,
    make_customer_headers,
    ApiErrorId,
    TEST_USERS,
    api_client,
)
from test_helpers.factories import (
    create_inventory_item_payload,
    create_customer_payload,
    create_warranty_claim_payload,
)

SA = TEST_USERS["sales_associate_headers"]
GS = TEST_USERS["goldsmith_headers"]
SM = TEST_USERS["store_manager_headers"]


def test_sales_associate_cannot_create_inventory_item(api):
    """PRD §2.1: "If both headers are present and well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /inventory-items authorizes only StoreManager.

    Design: Corner/rbac/salesassociate_cannot_create_inventory_item
    """
    res = api.create_inventory_item(
        create_inventory_item_payload(sku="RBAC-1", title="Ring", metal_karat="K18",
                                      list_price_cents=100000),
        SA,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_goldsmith_cannot_pass_qc(api):
    """PRD §2.1: "If both headers are present and well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /repair-tickets/{id}/pass-qc authorizes only StoreManager.

    Design: Corner/rbac/goldsmith_cannot_pass_qc
    """
    ticket, _ = drive_repair_ticket_to_qc_no_parts(0, 5000, repair_kind="POLISH")
    assert ticket["status"] == "QC"
    res = api.pass_qc_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, GS)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_customer_can_submit_warranty_claim(api):
    """PRD §2.1: "A `Customer` is the end customer, limited to read-only self-service plus the
    ability to submit a warranty claim."
    PRD §3.8: "A claim is submitted — by a sales associate, manager, or the customer
    themselves — against an `inventory_item_id`, a `customer_id`, and a free-text
    `defect_description`. A new claim is `SUBMITTED`."

    Design: Corner/rbac/customer_can_submit_warranty_claim
    """
    customer = create_customer(full_name="Self Serve", email="ss@x.com", phone="555-1022")
    item = create_inventory_item(sku="CUST-WC", title="Ring", metal_karat="K18",
                                 list_price_cents=200000)
    res = api.create_warranty_claim(
        create_warranty_claim_payload(item["id"], customer["id"], defect_description="Tarnish"),
        make_customer_headers(customer["id"]),
    )
    claim = validate_success(res, 201)
    assert claim["status"] == "SUBMITTED"


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "Every request to the API must carry two headers identifying the caller:
    `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is
    rejected with `ERR_MISSING_AUTH` (HTTP 401) before any other processing."

    Design: Corner/rbac/missing_auth_header_returns_401
    """
    res = api.create_customer(
        create_customer_payload(full_name="No Auth", email="na@x.com", phone="555-1023"),
        {},
    )
    validate_error(res, ApiErrorId.ERR_MISSING_AUTH.value, expected_status=401)
