"""API fundamentals: response envelope, pagination defaults, not-found, auth."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_brokerage_payload,
    create_vessel_payload,
    setup_active_listing,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_success_envelope_carries_request_id_and_object_type(
    api, platform_admin_headers
):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`." and "The `response_type` is either
    "object" for a single resource or "array" for a list of resources."

    Design: Corner/endpoints/response_envelope_shape_on_success
    """
    created = validate_success(
        api.create_brokerage(create_brokerage_payload(), platform_admin_headers), 201
    )
    res = api.get_brokerage(created["id"], platform_admin_headers)
    body = res.json()
    assert res.status_code == 200
    request_id = body["meta"]["api_request_id"]
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"api_request_id must start with req_, got {request_id!r}"
    )
    assert body["response_type"] == "object"
    assert body["data"]["id"] == created["id"]


def test_listings_list_uses_pagination_defaults(api, platform_admin_headers):
    """PRD §2.3: "`limit` defaults to 10, must be at least 1, and may not exceed
    100; `offset` defaults to 0." and "the `meta` block of a list response carries
    the four pagination fields `limit`, `offset`, `total_count`, and `has_more`"

    Design: Corner/endpoints/listings_list_pagination_defaults
    """
    setup_active_listing()
    res = api.list_listings(platform_admin_headers)
    data, meta = validate_paginated(res)
    assert len(data) == 1, f"expected exactly the one created listing, got {len(data)}"
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_get_listing_with_unknown_id_returns_not_found(api, platform_admin_headers):
    """PRD §2.4: "the first path segment that fails to resolve yields
    `ERR_NOT_FOUND` (HTTP 404) before any deeper segment is examined."

    Design: Corner/entities/listing_get_not_found_returns_404
    """
    res = api.get_listing(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_missing_identity_headers_rejected_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role outside
    the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_missing_role_header
    """
    # No identity headers at all.
    res = api.get_brokerage(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
    # Role header present but X-User-ID missing.
    res2 = api.get_brokerage(
        NON_EXISTENT_UUID,
        headers={"X-User-Role": "PlatformAdmin", "Content-Type": "application/json"},
    )
    validate_error(res2, ApiErrorId.ERR_UNAUTHENTICATED)
    # Role outside the declared set.
    res3 = api.get_brokerage(
        NON_EXISTENT_UUID,
        headers={
            "X-User-ID": "test-admin-1",
            "X-User-Role": "SuperUser",
            "Content-Type": "application/json",
        },
    )
    validate_error(res3, ApiErrorId.ERR_UNAUTHENTICATED)
