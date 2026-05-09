"""Response envelope, pagination, and authentication header sanity tests.

Pinned to PRD §2.1 (auth headers + roles), §2.2 (envelope), §2.3 (pagination).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    build_user_headers, TEST_USERS, create_repair_shop_payload,
    create_policy_payload, create_adjuster_payload,
    create_repair_shop, create_adjuster, create_policy,
    days_ago, days_ahead,
)


# ─── §2.2 envelope ────────────────────────────────────────────────
def test_create_repair_shop_returns_object_envelope(api, admin_headers):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body" with response_type
    "object" for a single resource.

    Claim: POST /repair-shops returns the success envelope, response_type=object.
    """
    res = api.create_repair_shop(create_repair_shop_payload(
        name="Envelope Shop", tax_id=f"TAX-ENV-{NON_EXISTENT_UUID[:8]}"
    ), admin_headers)
    body = res.json()
    assert res.status_code == 201
    assert body["response_type"] == "object"
    assert "meta" in body and "api_request_id" in body["meta"]
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in body["meta"]
    assert "data" in body and isinstance(body["data"], dict)


def test_list_endpoint_returns_array_envelope(api, admin_headers):
    """PRD §2.2: response_type "object" for a single resource or "array" for
    a list of resources.

    Claim: GET /adjusters returns an envelope with response_type=array and
    pagination fields in meta.
    """
    create_adjuster(full_name="List Adjuster")
    res = api.list_adjusters(admin_headers)
    body = res.json()
    assert res.status_code == 200
    assert body["response_type"] == "array"
    assert isinstance(body["data"], list)
    for k in ("limit", "offset", "total_count", "has_more"):
        assert k in body["meta"], f"meta missing pagination key {k}"


def test_error_response_envelope_shape(api):
    """PRD §2.2: error envelope carries `meta` with api_request_id and
    api_request_timestamp; data has error_id and message; response_type=error.

    Claim: missing auth headers triggers ERR_AUTH_REQUIRED with the proper
    error envelope.
    """
    res = api.list_adjusters({})  # no headers
    body = res.json()
    assert body["response_type"] == "error"
    assert "data" in body and "error_id" in body["data"] and "message" in body["data"]
    assert body["data"]["error_id"] == "ERR_AUTH_REQUIRED"


# ─── §2.1 auth header presence ────────────────────────────────────
def test_missing_user_id_header_rejected(api):
    """PRD §2.1: "Every request to the API must carry two HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring
    their operational capacity. Requests missing or malformed in either
    header are rejected with `ERR_AUTH_REQUIRED`."

    Claim: missing X-User-ID -> ERR_AUTH_REQUIRED.
    """
    res = api.list_adjusters({"X-User-Role": "PlatformAdmin"})
    validate_error(res, "ERR_AUTH_REQUIRED")


def test_missing_user_role_header_rejected(api):
    """PRD §2.1: "Every request to the API must carry two HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring
    their operational capacity. Requests missing or malformed in either
    header are rejected with `ERR_AUTH_REQUIRED`."

    Claim: missing X-User-Role -> ERR_AUTH_REQUIRED.
    """
    res = api.list_adjusters({"X-User-ID": "test-user"})
    validate_error(res, "ERR_AUTH_REQUIRED")


# ─── §2.1 role authorisation ──────────────────────────────────────
def test_unknown_role_value_rejected(api):
    """PRD §2.1: "The system recognises five roles, spelled exactly as
    follows: `Customer`, `Adjuster`, `Reviewer`, `PayoutOfficer`, and
    `PlatformAdmin`. A request whose `X-User-Role` is not one of these
    values, or whose role is not authorised for the targeted endpoint,
    is rejected with `ERR_FORBIDDEN`."

    Claim: an unknown role value -> ERR_FORBIDDEN.
    """
    res = api.list_adjusters(build_user_headers("u", "Unknown"))
    validate_error(res, "ERR_FORBIDDEN")


def test_known_role_not_authorized_for_endpoint(api):
    """PRD §2.1: "The system recognises five roles, spelled exactly as
    follows: `Customer`, `Adjuster`, `Reviewer`, `PayoutOfficer`, and
    `PlatformAdmin`. A request whose `X-User-Role` is not one of these
    values, or whose role is not authorised for the targeted endpoint,
    is rejected with `ERR_FORBIDDEN`."

    Claim: Customer calling POST /adjusters (PlatformAdmin-only) -> ERR_FORBIDDEN.
    """
    res = api.create_adjuster(
        create_adjuster_payload(license_number="LIC-FORB-1"),
        build_user_headers("any-customer", "Customer"),
    )
    validate_error(res, "ERR_FORBIDDEN")


# ─── §2.3 pagination ──────────────────────────────────────────────
def test_pagination_default_limit_and_offset(api, admin_headers):
    """PRD §2.3: "The `limit` parameter is the maximum number of items to
    return; it defaults to 10, must be at least 1, and must not exceed 100.
    The `offset` parameter is the number of items to skip from the front
    of the result set; it defaults to 0 and must not be negative."

    Claim: list with no params -> meta.limit==10, meta.offset==0.
    """
    create_adjuster(full_name="Pagination 1")
    res = api.list_adjusters(admin_headers)
    data, meta = validate_paginated(res)
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_pagination_invalid_limit_too_high(api, admin_headers):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 to 100, or a
    negative `offset`, is rejected with `ERR_INVALID_PAGINATION`."

    Claim: limit=101 -> ERR_INVALID_PAGINATION.
    """
    res = api.list_adjusters(admin_headers, params={"limit": 101})
    validate_error(res, "ERR_INVALID_PAGINATION")


def test_pagination_invalid_limit_zero(api, admin_headers):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 to 100, or a
    negative `offset`, is rejected with `ERR_INVALID_PAGINATION`."

    Claim: limit=0 -> ERR_INVALID_PAGINATION.
    """
    res = api.list_adjusters(admin_headers, params={"limit": 0})
    validate_error(res, "ERR_INVALID_PAGINATION")


def test_pagination_invalid_offset_negative(api, admin_headers):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 to 100, or a
    negative `offset`, is rejected with `ERR_INVALID_PAGINATION`."

    Claim: offset=-1 -> ERR_INVALID_PAGINATION.
    """
    res = api.list_adjusters(admin_headers, params={"offset": -1})
    validate_error(res, "ERR_INVALID_PAGINATION")


def test_pagination_limit_max_inclusive(api, admin_headers):
    """PRD §2.3: "must not exceed 100" — 100 itself is valid.

    Claim: limit=100 succeeds (boundary inclusive).
    """
    res = api.list_adjusters(admin_headers, params={"limit": 100})
    data, meta = validate_paginated(res)
    assert meta["limit"] == 100


# ─── §2.5 path-referenced existence ───────────────────────────────
def test_get_policy_not_found_returns_err_not_found(api, admin_headers):
    """PRD §2.5: "Path-referenced resources are validated left-to-right.
    For a request such as the appeal-decision endpoint, the server first
    verifies that the `Claim` named by the leading path segment exists,
    then that the `Appeal` named by the subsequent segment exists and
    belongs to that claim; the first identifier that fails resolution
    causes the request to be rejected with `ERR_NOT_FOUND` before any
    later identifier or any business rule is evaluated."

    Claim: GET /policies/{nonexistent} -> ERR_NOT_FOUND.
    """
    res = api.get_policy(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_get_claim_not_found_returns_err_not_found(api, admin_headers):
    """PRD §2.5: "the first identifier that fails resolution causes the
    request to be rejected with `ERR_NOT_FOUND` before any later identifier
    or any business rule is evaluated."

    Claim: GET /claims/{nonexistent} -> ERR_NOT_FOUND.
    """
    res = api.get_claim(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, "ERR_NOT_FOUND")
