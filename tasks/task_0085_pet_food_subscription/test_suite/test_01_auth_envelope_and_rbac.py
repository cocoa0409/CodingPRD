"""Authentication, RBAC, response envelope, and pagination (PRD §2.1–§2.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_customer_payload,
    create_recipe_payload,
    create_warehouse_payload,
    is_iso8601_timestamp,
    make_customer_headers,
    setup_customer_with_pet,
    setup_verified_customer,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# §2.1 — Missing/invalid user-context headers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("headers", [
    {},
    {"X-User-ID": "test-user-1"},
    {"X-User-Role": "Customer"},
    {"X-User-ID": "", "X-User-Role": "Customer"},
    {"X-User-ID": "test-user-1", "X-User-Role": ""},
    {"X-User-ID": "test-user-1", "X-User-Role": "UnknownRole"},
])
def test_missing_or_invalid_user_context_headers_rejected(api, headers):
    """PRD §2.1: "If either header is missing, or X-User-Role is not
    one of the role names enumerated below, the request is rejected
    with HTTP 400 and the error id
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."
    """
    res = api.create_customer(create_customer_payload(), headers)
    validate_error(
        res,
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
    )


# ---------------------------------------------------------------------------
# §2.1 — RBAC: wrong role for endpoint
# ---------------------------------------------------------------------------
def test_create_recipe_rejects_customer_role(api,
                                             customer_fallback_headers):
    """PRD §2.1: "When the headers are present and valid but the role
    is not authorized for the requested endpoint per the §4 RBAC
    matrix, the request is rejected with HTTP 403 and
    ERR_INSUFFICIENT_PERMISSIONS."
    PRD §4: POST /recipes Authorized Role(s): AdminOps.
    """
    res = api.create_recipe(
        create_recipe_payload(), customer_fallback_headers,
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_create_warehouse_rejects_customer_role(api,
                                                customer_fallback_headers):
    """PRD §2.1: "the request is rejected with HTTP 403 and
    ERR_INSUFFICIENT_PERMISSIONS."
    PRD §4: POST /warehouses Authorized Role(s): AdminOps.
    """
    res = api.create_warehouse(
        create_warehouse_payload(), customer_fallback_headers,
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_advance_clock_rejects_customer_role(api,
                                             customer_fallback_headers):
    """PRD §4: POST /_clock/advance Authorized Role(s): AdminOps."""
    res = api.advance_clock({"by_hours": 1}, customer_fallback_headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_audit_log_read_rejects_customer_role(api,
                                              customer_fallback_headers):
    """PRD §2.9: "the read endpoint is exposed only to AdminOps."
    PRD §4: GET /audit-logs Authorized Role(s): AdminOps.
    """
    res = api.list_audit_logs(customer_fallback_headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ---------------------------------------------------------------------------
# §2.1 — Customer ownership trail
# ---------------------------------------------------------------------------
def test_customer_cannot_read_another_customers_subscription(api):
    """PRD §2.1: "A Customer may only act on resources whose ownership
    trail terminates at their own id; otherwise the request is
    rejected with ERR_INSUFFICIENT_PERMISSIONS."
    """
    from test_helpers import (
        create_draft_subscription, verify_subscription_address,
        activate_subscription,
    )

    cust_a, pet_a = setup_customer_with_pet()
    sub_a = create_draft_subscription(cust_a, pet_a)
    sub_a = verify_subscription_address(cust_a, sub_a)
    sub_a = activate_subscription(cust_a, sub_a)

    # Second customer attempts to read first customer's subscription.
    cust_b = setup_verified_customer()
    res = api.get_subscription(
        sub_a["id"], make_customer_headers(cust_b["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_customer_cannot_create_pet_under_another_customer(api):
    """PRD §2.1 ownership trail: 'ownership checks on any resource
    that ultimately references a Customer (a Pet via customer_id ...)
    compare the resource's customer_id ... to X-User-ID.'"""
    from test_helpers import create_pet_payload

    cust_a = setup_verified_customer()
    cust_b = setup_verified_customer()
    # Customer B attempts to create a pet under Customer A.
    res = api.create_pet(
        cust_a["id"],
        create_pet_payload(),
        make_customer_headers(cust_b["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ---------------------------------------------------------------------------
# §2.2 — Standard Success Response envelope
# ---------------------------------------------------------------------------
def test_success_response_envelope_shape(api):
    """PRD §2.2: success envelope contains meta.api_request_id (starts
    with 'req_'), meta.api_request_timestamp (ISO 8601 UTC with three
    fractional digits), response_type ('object' or 'array'), and data.
    """
    res = api.create_customer(
        create_customer_payload(), TEST_USERS["customer_headers"],
    )
    # Status will be 201; envelope shape is enforced.
    body = res.json()
    assert "meta" in body
    assert "response_type" in body
    assert "data" in body
    assert body["response_type"] == "object"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"PRD §2.2: api_request_id must start with 'req_'; got "
        f"{meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))


def test_error_response_envelope_shape(api):
    """PRD §2.2: error envelope: meta carries only api_request_id and
    api_request_timestamp; response_type == 'error'; data carries
    error_id and message.
    """
    res = api.create_customer(create_customer_payload(), {})
    body = res.json()
    assert body.get("response_type") == "error"
    data = body.get("data", {})
    assert data.get("error_id") == (
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value
    )
    assert isinstance(data.get("message"), str)
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))


# ---------------------------------------------------------------------------
# §2.3 — Pagination
# ---------------------------------------------------------------------------
def test_pagination_envelope_includes_required_fields(api):
    """PRD §2.3: 'Every list response includes the four pagination
    fields limit, offset, total_count, and has_more in the meta block.'
    """
    res = api.list_recipes(TEST_USERS["admin_ops_headers"])
    data, meta = validate_paginated(res)
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, (
            f"PRD §2.3: meta must include {key!r}; got keys "
            f"{list(meta.keys())}"
        )
    assert isinstance(data, list)


def test_pagination_limit_default_is_10(api):
    """PRD §2.3: 'limit defaults to 10 when omitted.'"""
    res = api.list_recipes(TEST_USERS["admin_ops_headers"])
    _, meta = validate_paginated(res)
    assert meta["limit"] == 10, (
        f"PRD §2.3 default limit must be 10; got {meta['limit']}"
    )


@pytest.mark.parametrize("limit", [0, -1, 101, 1000])
def test_pagination_limit_out_of_range_rejected(api, limit):
    """PRD §2.3: 'limit defaults to 10 ... with a minimum of 1 and a
    maximum of 100; values outside this range are rejected with
    ERR_INVALID_REQUEST.'
    """
    res = api.list_recipes(
        TEST_USERS["admin_ops_headers"], params={"limit": limit},
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# §2.6 — Nested resource resolution: left-to-right 404
# ---------------------------------------------------------------------------
def test_left_to_right_existence_check_pet_not_found(api):
    """PRD §2.6: 'Path parameters are validated left to right.'
    With a valid customerId and a missing petId, the petId surfaces a
    PET_NOT_FOUND, not the deeper checks.
    """
    customer = setup_verified_customer()
    res = api.get_pet(
        customer["id"], NON_EXISTENT_UUID,
        make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PET_NOT_FOUND.value)


def test_left_to_right_existence_check_customer_not_found(api):
    """PRD §2.6: 'The first missing id surfaces the corresponding 404
    from the catalog ERR_CUSTOMER_NOT_FOUND ... and the request returns
    without checking the remaining ids.'

    Use a NON_EXISTENT_UUID customerId. Because authentication runs at
    priority 1 and the customer ownership check comes from §2.6 with
    matching X-User-ID, we use a fallback Customer header here purely
    to probe the 404 layer once auth passes.
    """
    # Customer fallback id doesn't match the path customerId; per §2.1
    # ownership the implementation surfaces 403 OR 404 depending on
    # check order. PRD §2.7 pins existence-after-auth and after RBAC,
    # so to isolate the 404 we use AdminOps (read-share on customer).
    res = api.get_customer(
        NON_EXISTENT_UUID, TEST_USERS["admin_ops_headers"],
    )
    validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)
