"""Authentication, authorisation, and envelope conformance tests.

PRD coverage: §2.1 auth headers, §2.2 envelope, §2.3 pagination,
§2.6 validation ordering (auth before everything).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_vehicle_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Auth header presence (PRD §2.1)
# ===========================================================================
def test_auth_missing_when_no_headers(api):
    """PRD §2.1: 'A request that omits either header, or sends them
    empty, is rejected with ERR_AUTH_MISSING.'"""
    resp = api.list_vehicles(headers={})
    validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


def test_auth_missing_when_user_id_blank(api):
    """PRD §2.1: 'A request that omits either header, or sends them
    empty, is rejected with ERR_AUTH_MISSING.'"""
    resp = api.list_vehicles(
        headers={"X-User-ID": "", "X-User-Role": "CARRIER"},
    )
    validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


def test_auth_missing_when_role_blank(api):
    """PRD §2.1: 'A request that omits either header, or sends them
    empty, is rejected with ERR_AUTH_MISSING.'"""
    resp = api.list_vehicles(
        headers={"X-User-ID": "someone", "X-User-Role": ""},
    )
    validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


def test_auth_missing_when_only_user_id_present(api):
    """PRD §2.1: 'A request that omits either header ... is rejected
    with ERR_AUTH_MISSING.'"""
    resp = api.list_vehicles(headers={"X-User-ID": "someone"})
    validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


# ===========================================================================
# Forbidden role (PRD §2.1)
# ===========================================================================
def test_forbidden_for_unrecognized_role(api):
    """PRD §2.1: 'A request whose X-User-Role is not one of the seven
    recognised roles, or whose role is not authorised for the endpoint,
    is rejected with ERR_FORBIDDEN.'"""
    resp = api.list_vehicles(
        headers={"X-User-ID": "x", "X-User-Role": "PIRATE"},
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_forbidden_when_role_not_authorized_for_endpoint(
    api, shipper_headers,
):
    """PRD §2.1: 'A request whose X-User-Role ... is not authorised for
    the endpoint, is rejected with ERR_FORBIDDEN.'

    POST /vehicles is restricted to CARRIER (PRD §4 table) — a SHIPPER
    call must be rejected with ERR_FORBIDDEN.
    """
    resp = api.create_vehicle(create_vehicle_payload(), shipper_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_forbidden_when_dispatcher_creates_vehicle(api, dispatcher_headers):
    """PRD §2.1 + §4: POST /vehicles is authorised for CARRIER only."""
    resp = api.create_vehicle(create_vehicle_payload(), dispatcher_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_forbidden_when_driver_dispatches(api, driver_headers):
    """PRD §2.1 + §4: POST /transport-tasks/{id}/dispatch is restricted
    to DISPATCHER. A DRIVER call must be rejected with ERR_FORBIDDEN."""
    resp = api.dispatch_task(NON_EXISTENT_UUID, driver_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Envelope shape (PRD §2.2)
# ===========================================================================
def test_success_envelope_shape_on_vehicle_create(api, carrier_headers):
    """PRD §2.2: 'All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body'
    with meta containing api_request_id and api_request_timestamp."""
    resp = api.create_vehicle(create_vehicle_payload(), carrier_headers)
    body = resp.json()
    assert body["response_type"] == "object"
    assert "meta" in body and "data" in body
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        "PRD §2.2: 'The api_request_id is a server-generated unique "
        "identifier for the request that starts with req_.'"
    )
    assert isinstance(meta.get("api_request_timestamp"), str)


def test_error_envelope_shape_on_auth_missing(api):
    """PRD §2.2: 'All error API responses (4xx status codes) follow
    this standard envelope format ... response_type: error.'"""
    resp = api.list_vehicles(headers={})
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == ApiErrorId.ERR_AUTH_MISSING.value
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
def test_pagination_limit_below_min_rejected(api, carrier_headers):
    """PRD §2.3: 'The default limit is 10, the minimum is 1, and the
    maximum is 100; values outside this range are rejected with
    ERR_VALIDATION.'"""
    resp = api.list_vehicles(carrier_headers, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_pagination_limit_above_max_rejected(api, carrier_headers):
    """PRD §2.3: 'the maximum is 100; values outside this range are
    rejected with ERR_VALIDATION.'"""
    resp = api.list_vehicles(carrier_headers, params={"limit": 101})
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_pagination_meta_present_on_list(api, carrier_headers):
    """PRD §2.3: 'The pagination block of meta exposes limit, offset,
    total_count, and has_more on every list response.'"""
    resp = api.list_vehicles(carrier_headers, params={"limit": 1})
    body = resp.json()
    meta = body["meta"]
    for k in ("limit", "offset", "total_count", "has_more"):
        assert k in meta, f"PRD §2.3 missing pagination key: {k}"
