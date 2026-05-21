"""Auth headers, response envelope, pagination — PRD §2.1, §2.2, §2.3."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
    create_brokerage_payload,
    create_shipper_payload,
    setup_brokerage_with_shipper,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 — header presence and well-formedness
# ===========================================================================
def test_missing_user_id_header_rejected(api):
    """PRD §2.1: "A request that omits either header, or carries a
    malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Claim: missing X-User-ID -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    """
    res = api.create_brokerage(create_brokerage_payload(),
                               {"X-User-Role": "PlatformAdmin"})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


def test_missing_user_role_header_rejected(api):
    """PRD §2.1: "A request that omits either header, or carries a
    malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Claim: missing X-User-Role -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    """
    res = api.create_brokerage(create_brokerage_payload(),
                               {"X-User-ID": "platform-admin-0001"})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


def test_empty_user_role_header_rejected(api):
    """PRD §2.1: "A request that omits either header, or carries a
    malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Claim: empty role -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    """
    res = api.create_brokerage(create_brokerage_payload(),
                               {"X-User-ID": "x", "X-User-Role": ""})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


def test_unknown_role_value_rejected(api):
    """PRD §2.1: "A request that omits either header, or carries a
    malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Claim: a role string outside the five enumerated roles is malformed.
    """
    res = api.create_brokerage(create_brokerage_payload(),
                               {"X-User-ID": "x", "X-User-Role": "Wizard"})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


def test_role_not_authorized_for_endpoint(api, broker_ops_headers):
    """PRD §2.1: "A request that carries a well-formed role which is
    not authorised for the endpoint is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    PRD §4: POST /brokerages is restricted to PlatformAdmin.
    Claim: BrokerOps posting to /brokerages -> ERR_INSUFFICIENT_PERMISSIONS.
    """
    res = api.create_brokerage(create_brokerage_payload(), broker_ops_headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


# ===========================================================================
# §2.2 — success and error envelopes
# ===========================================================================
def test_success_envelope_shape(api, platform_admin_headers):
    """PRD §2.2: "All successful API responses ... follow this standard
    envelope format in their JSON body" with `meta.api_request_id` (`req_`),
    `meta.api_request_timestamp`, `response_type` and `data` keys.

    Claim: envelope keys are present and api_request_id has the req_ prefix.
    """
    res = api.create_brokerage(create_brokerage_payload(),
                               platform_admin_headers)
    body = res.json()
    assert "meta" in body
    assert "data" in body
    assert "response_type" in body
    meta = body["meta"]
    assert meta.get("api_request_id", "").startswith("req_"), (
        f"api_request_id must start with req_, got {meta.get('api_request_id')!r}"
    )
    assert "api_request_timestamp" in meta


def test_error_envelope_shape(api):
    """PRD §2.2: error envelope carries `data.error_id` and `data.message`.

    Claim: a 400-on-missing-headers response carries the documented shape.
    """
    res = api.create_brokerage(create_brokerage_payload(), {})
    body = res.json()
    assert body.get("response_type") == "error"
    assert "data" in body
    assert "error_id" in body["data"]
    assert "message" in body["data"]
    assert isinstance(body["data"]["message"], str)


# ===========================================================================
# §2.3 — pagination defaults, bounds, has_more.
# ===========================================================================
def test_list_pagination_defaults_and_bounds(api, broker_ops_headers):
    """PRD §2.3: "`limit` defaults to 10, has a minimum value of 1 and a
    maximum value of 100; a request that specifies a value outside that
    range is rejected with `ERR_INVALID_REQUEST`."

    Claim: limit defaults, limits below 1 or above 100 -> ERR_INVALID_REQUEST.
    """
    brokerage, shipper = setup_brokerage_with_shipper()

    # Default — should succeed; the result is a list with up to 10 entries.
    data, meta = validate_paginated(
        api.list_shippers(brokerage["id"], broker_ops_headers),
    )
    assert meta["limit"] == 10

    # Below minimum.
    res = api.list_shippers(brokerage["id"], broker_ops_headers,
                            params={"limit": PAGINATION_MIN_LIMIT - 1})
    validate_error(res, "ERR_INVALID_REQUEST")

    # Above maximum.
    res = api.list_shippers(brokerage["id"], broker_ops_headers,
                            params={"limit": PAGINATION_MAX_LIMIT + 1})
    validate_error(res, "ERR_INVALID_REQUEST")


def test_list_pagination_has_more_semantics(api, broker_ops_headers):
    """PRD §2.3: "`has_more` (true when `offset + limit < total_count`, false otherwise)."

    Claim: build 3 shippers, list with limit=1 -> has_more True; offset
    past the total -> empty list, has_more False.
    """
    brokerage, _ = setup_brokerage_with_shipper()
    api.create_shipper(brokerage["id"],
                       create_shipper_payload(company_name="Two"),
                       broker_ops_headers)
    api.create_shipper(brokerage["id"],
                       create_shipper_payload(company_name="Three"),
                       broker_ops_headers)

    data, meta = validate_paginated(
        api.list_shippers(brokerage["id"], broker_ops_headers,
                          params={"limit": 1, "offset": 0}),
    )
    assert len(data) == 1
    assert meta["total_count"] >= 3
    assert meta["has_more"] is True

    data, meta = validate_paginated(
        api.list_shippers(brokerage["id"], broker_ops_headers,
                          params={"limit": 1, "offset": 99_999}),
    )
    assert len(data) == 0
    assert meta["has_more"] is False


# ===========================================================================
# §2.8 — Tenancy / nested resource resolution.
# ===========================================================================
def test_brokerage_not_found(api, platform_admin_headers):
    """PRD §2.8: "The brokerageId is checked first; an unresolved value
    yields `ERR_BROKERAGE_NOT_FOUND`."

    Claim: GET /brokerages/<random uuid> -> ERR_BROKERAGE_NOT_FOUND.
    """
    res = api.get_brokerage(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(res, "ERR_BROKERAGE_NOT_FOUND")


def test_shipper_not_found_under_brokerage(api, broker_ops_headers):
    """PRD §2.8: "Nested segments ... are then resolved in path order,
    each producing its own ERR_<RESOURCE>_NOT_FOUND (for example
    `ERR_SHIPPER_NOT_FOUND` ...)."

    Claim: GET /brokerages/B/shippers/<random> -> ERR_SHIPPER_NOT_FOUND.
    """
    brokerage, _ = setup_brokerage_with_shipper()
    res = api.get_shipper(brokerage["id"], NON_EXISTENT_UUID,
                          broker_ops_headers)
    validate_error(res, "ERR_SHIPPER_NOT_FOUND")


def test_shipper_belonging_to_other_brokerage_is_not_found(
    api, broker_ops_headers,
):
    """PRD §2.8: "A nested resource that belongs to a different parent
    than the one named in the path is treated as not found rather than
    as a permission violation — for example, a `Shipper` whose `brokerage_id`
    does not match the path's brokerageId yields `ERR_SHIPPER_NOT_FOUND`."

    Claim: a Shipper from brokerage A, looked up under brokerage B,
    yields ERR_SHIPPER_NOT_FOUND.
    """
    brokerage_a, shipper_a = setup_brokerage_with_shipper()
    brokerage_b, _ = setup_brokerage_with_shipper()
    res = api.get_shipper(brokerage_b["id"], shipper_a["id"],
                          broker_ops_headers)
    validate_error(res, "ERR_SHIPPER_NOT_FOUND")
