"""Authentication, authorization, response envelope shape, and pagination."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_catalog_item,
    create_catalog_item_payload,
    create_customer,
    create_customer_payload,
    create_quoted_reservation,
    make_customer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _ops():
    return TEST_USERS["ops_admin_headers"]


def test_list_catalog_missing_auth_headers_returns_unauthenticated(api):
    """PRD 2.1: "A request missing either header, or presenting a role string
    that is not one of the declared roles, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    A request with neither X-User-Role nor X-User-ID is rejected before any
    role check.

    Design: Corner/validations/list_catalog_missing_auth_headers_returns_unauthenticated
    """
    res = api.list_catalog_items(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_customer_cannot_create_catalog_item(api):
    """PRD 2.1: "A request whose role is recognized but not permitted for the
    endpoint — or that fails an entity-backed ownership check — is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."
    PRD 4: the catalog-item creation row authorizes OperationsAdmin only
    ("Create a catalog item | OperationsAdmin").

    Design: Corner/rbac/customer_cannot_create_catalog_item
    """
    customer = create_customer()
    res = api.create_catalog_item(
        create_catalog_item_payload(), make_customer_headers(customer["id"])
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_customer_cannot_read_other_customers_reservation(api):
    """PRD 2.1: "A Customer may only access reservations, reservation lines,
    extension requests, deposit ledger entries, and damage claims whose
    reservation's `customer_id` equals their own `X-User-ID`."
    PRD 2.1: "A request whose role is recognized but not permitted for the
    endpoint — or that fails an entity-backed ownership check — is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    Customer B reading Customer A's reservation is rejected ERR_FORBIDDEN even
    though the reservation exists.

    Design: Corner/rbac/customer_cannot_read_other_customers_reservation
    """
    cust_a = create_customer()
    cust_b = create_customer()
    catalog = create_catalog_item()
    reservation = create_quoted_reservation(
        cust_a["id"], lines=[{"catalog_item_id": catalog["id"]}]
    )
    res = api.get_reservation(
        reservation["id"], make_customer_headers(cust_b["id"])
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_response_envelope_shape_on_success_and_error(api, anonymous_headers):
    """PRD 2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    The create response carries meta + response_type "object" + the Customer in
    data; the not-found response carries response_type "error" with
    data.error_id and data.message.

    Design: Corner/endpoints/response_envelope_shape_on_success_and_error
    """
    create_res = api.create_customer(
        create_customer_payload(full_name="Vic We"), anonymous_headers
    )
    assert create_res.status_code == 201
    body = create_res.json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] == "object"
    assert isinstance(body["data"], dict) and "id" in body["data"]

    err_res = api.get_reservation(NON_EXISTENT_UUID, _ops())
    validate_error(err_res, "ERR_RESERVATION_NOT_FOUND", expected_status=404)
    err_body = err_res.json()
    assert err_body["response_type"] == "error"
    assert isinstance(err_body["data"]["message"], str)
    assert len(err_body["data"]["message"].strip()) > 0


def test_catalog_list_pagination_limit_offset(api):
    """PRD 2.3: "List endpoints accept the query parameters `limit` and
    `offset`. `limit` defaults to 10, must be at least 1, and may not exceed
    100. `offset` defaults to 0. List responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object."

    With three catalog items: limit=2&offset=0 returns 2 rows with total_count
    3 and has_more true; limit=2&offset=2 returns the last row with has_more
    false.

    Design: Corner/endpoints/catalog_list_pagination_limit_offset
    """
    create_catalog_item(name="Crib AP")
    create_catalog_item(
        name="Stroller AQ",
        category="STROLLER",
        daily_rate_cents=1500,
        deposit_amount_cents=8000,
        weight_kg=8.0,
        cleaning_turnaround_hours=12,
    )
    create_catalog_item(
        name="CarSeat AR",
        category="CARSEAT",
        daily_rate_cents=1200,
        deposit_amount_cents=9000,
        weight_kg=6.0,
        cleaning_turnaround_hours=12,
    )
    page1, meta1 = validate_paginated(
        api.list_catalog_items(_ops(), params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_catalog_items(_ops(), params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
