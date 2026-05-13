"""Auth headers, response envelope, pagination, and existence checks
(PRD §2.1, §2.2, §2.3, §2.4, §2.6).

These are framework-of-the-API tests: every endpoint observes them.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    OPERATOR_HEADERS,
    assert_response_envelope_meta,
    build_user_headers,
    create_personnel_payload,
    create_service_item_payload,
    setup_basic_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


# =============================================================================
# Authentication / authorization (PRD §2.1)
# =============================================================================


def test_missing_user_role_header_rejected(api):
    """PRD §2.1: "A request that omits or mis-spells either header is rejected
    with ERR_UNAUTHENTICATED (HTTP 401)."

    Claim: omitting X-User-Role returns ERR_UNAUTHENTICATED with HTTP 401.
    """
    res = api.create_personnel(create_personnel_payload(), {"X-User-ID": "u-1"})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_empty_headers_rejected(api):
    """PRD §2.1: "A request that omits or mis-spells either header is rejected
    with ERR_UNAUTHENTICATED (HTTP 401)."

    Claim: passing entirely empty headers returns ERR_UNAUTHENTICATED.
    """
    res = api.list_personnel({})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_customer_cannot_create_personnel(api):
    """PRD §2.1: "A request whose role is not permitted to invoke the requested
    endpoint is rejected with ERR_FORBIDDEN (HTTP 403)."

    Claim: a Customer calling POST /dsd/personnel (PlatformOperator-only) gets
    ERR_FORBIDDEN with HTTP 403.
    """
    headers = build_user_headers("test-customer-rbac", "Customer")
    res = api.create_personnel(create_personnel_payload(), headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_personnel_cannot_create_service_item(api):
    """PRD §2.1: "A request whose role is not permitted to invoke the requested
    endpoint is rejected with ERR_FORBIDDEN (HTTP 403)."

    Claim: a ServicePersonnel calling POST /dsd/service-items (PlatformOperator-only) gets
    ERR_FORBIDDEN.
    """
    headers = build_user_headers("test-personnel-rbac", "ServicePersonnel")
    res = api.create_service_item(create_service_item_payload(), headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_personnel_acting_on_unassigned_order_not_assigned(api):
    """PRD §2.1: "When a ServicePersonnel invokes an order-action endpoint
    (accept, reject, check-in, complete, execution update), the server
    additionally verifies that Order.assigned_personnel_id equals X-User-ID;
    a mismatch is rejected with ERR_NOT_ASSIGNED (HTTP 403)."

    Claim: a ServicePersonnel other than the assignee that calls accept gets
    ERR_NOT_ASSIGNED 403.
    """
    from test_helpers import drive_order_to, make_personnel_headers

    ctx = setup_basic_scenario()
    order = drive_order_to(ctx, "DISPATCHED")
    other_headers = make_personnel_headers("a-completely-different-personnel-id")
    res = api.accept_order(order["id"], other_headers)
    validate_error(res, "ERR_NOT_ASSIGNED", expected_status=403)


# =============================================================================
# Response envelope (PRD §2.2)
# =============================================================================


def test_success_envelope_shape(api):
    """PRD §2.2: success responses carry meta.api_request_id (req_*) and
    meta.api_request_timestamp, plus response_type and data.

    Claim: a 201 response from POST /dsd/service-items has the
    "meta.api_request_id" prefixed with "req_" and a valid ISO 8601
    "meta.api_request_timestamp".
    """
    res = api.create_service_item(
        create_service_item_payload(name="Envelope test item"), OPERATOR_HEADERS
    )
    validate_success(res, expected_status=201)
    body = res.json()
    assert_response_envelope_meta(body)
    assert body["response_type"] == "object"


def test_error_envelope_shape_on_not_found(api):
    """PRD §2.2: error responses set response_type="error" and data.error_id.

    Claim: a 404 envelope has response_type "error" and data.error_id present.
    """
    res = api.get_personnel(NON_EXISTENT_UUID, OPERATOR_HEADERS)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)
    body = res.json()
    assert body["response_type"] == "error"
    assert "error_id" in body["data"]


# =============================================================================
# Existence / path resolution (PRD §2.6)
# =============================================================================


def test_get_personnel_not_found_returns_404(api):
    """PRD §2.6: "If a referenced entity does not exist, the request is
    rejected with ERR_NOT_FOUND (HTTP 404)."

    Claim: GET /dsd/personnel/{non_existent_id} → ERR_NOT_FOUND 404.
    """
    res = api.get_personnel(NON_EXISTENT_UUID, OPERATOR_HEADERS)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_get_customer_not_found_returns_404(api):
    """PRD §2.6: "If a referenced entity does not exist, the request is
    rejected with ERR_NOT_FOUND (HTTP 404)."

    Claim: GET /dsd/customers/{non_existent_id} → ERR_NOT_FOUND 404.
    """
    res = api.get_customer(NON_EXISTENT_UUID, OPERATOR_HEADERS)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# =============================================================================
# Pagination (PRD §2.3)
# =============================================================================


def test_list_personnel_pagination_envelope(api):
    """PRD §2.3: "The pagination metadata exposed in the success envelope's
    meta block consists of limit, offset, total_count (the unfiltered total
    matching the query), and has_more (true when more rows exist past the
    current window)."

    Claim: GET /dsd/personnel returns a meta block carrying limit, offset,
    total_count and has_more.
    """
    res = api.list_personnel(OPERATOR_HEADERS, params={"limit": 5, "offset": 0})
    data, meta = validate_paginated(res)
    assert isinstance(data, list)
    assert "limit" in meta and "offset" in meta
    assert "total_count" in meta and "has_more" in meta
    assert meta["limit"] == 5
    assert meta["offset"] == 0
    assert isinstance(meta["has_more"], bool)


# =============================================================================
# Common resource shape (PRD §2.4)
# =============================================================================


def test_service_item_carries_common_fields(api):
    """PRD §2.4: "Most entities additionally carry created_at, updated_at, and
    version. ... The version field is a positive integer that starts at 1 on
    creation."

    Claim: a freshly created ServiceItem carries version=1, created_at,
    updated_at, and a bare UUID id.
    """
    res = api.create_service_item(
        create_service_item_payload(name="Common-fields probe"), OPERATOR_HEADERS
    )
    body = validate_success(res, expected_status=201)
    assert body["version"] == 1
    assert "created_at" in body and "updated_at" in body
    # PRD §2.4 says id is a bare UUID with no type prefix.
    assert "-" in body["id"] and not body["id"].startswith("svc_")
