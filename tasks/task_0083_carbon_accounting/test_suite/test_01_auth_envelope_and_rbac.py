"""Authentication, RBAC, response envelope, and pagination (PRD §2.1–§2.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_organization_payload,
    is_iso8601_timestamp,
    setup_org_facility_period,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Missing or empty user-context headers (PRD §2.1)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("headers", [
    {},
    {"X-User-ID": "some-user"},
    {"X-User-Role": "PlatformAdmin"},
    {"X-User-ID": "", "X-User-Role": "PlatformAdmin"},
    {"X-User-ID": "some-user", "X-User-Role": ""},
])
def test_missing_or_empty_user_context_headers_rejected(api, headers):
    """PRD §2.1: "A request missing either header, or with either header
    empty, is rejected with ERR_AUTH_REQUIRED and HTTP 401."
    """
    res = api.create_organization(create_organization_payload(), headers)
    validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ---------------------------------------------------------------------------
# Forbidden roles on PlatformAdmin-exclusive endpoints (PRD §2.1, §4)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", [
    "DataSteward", "FactorManager", "Verifier", "Discloser",
])
def test_create_organization_forbidden_for_non_admin(api, role):
    """PRD §2.1: "A request whose role is not authorized for the
    requested endpoint is rejected with ERR_FORBIDDEN and HTTP 403."
    POST /organizations is PlatformAdmin-only (PRD §4).
    """
    headers = build_user_headers(f"user-{role.lower()}", role)
    res = api.create_organization(create_organization_payload(), headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_factor_create_forbidden_for_discloser(api, discloser_headers):
    """PRD §4: "POST /organizations/{org_id}/factors ... Authorized
    Role(s): FactorManager." Discloser is not in the list, so the call
    fails authorization."""
    # We need an org_id but the request is rejected before we touch it.
    res = api.create_factor(
        NON_EXISTENT_UUID, {"code": "X", "library": "IPCC_DEFAULT",
                            "gas_type": "CO2", "kg_per_unit": 1.0,
                            "uncertainty_rating": "LOW",
                            "effective_from": "2024-01-01T00:00:00.000Z",
                            "traceability_url": "x"},
        discloser_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_credit_create_forbidden_for_factor_manager(api,
                                                    factor_manager_headers):
    """PRD §4: "POST /organizations/{org_id}/credits ... Authorized
    Role(s): Discloser." FactorManager is not in the list."""
    res = api.create_credit(
        NON_EXISTENT_UUID,
        {"registry": "VCS", "serial_number": "S1",
         "vintage_year": 2024, "quantity_kg_co2e": 1.0,
         "linked_reduction_project_id": NON_EXISTENT_UUID,
         "reporting_period_id": NON_EXISTENT_UUID},
        factor_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_clock_advance_forbidden_for_steward(api, data_steward_headers):
    """PRD §4: "POST /_clock/advance ... Authorized Role(s):
    PlatformAdmin." DataSteward is not authorized.
    """
    res = api.advance_clock(
        {"to_timestamp": "2099-01-01T00:00:00.000Z"},
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Standard envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def test_success_envelope_shape(api, platform_admin_headers):
    """PRD §2.2: success body carries meta{api_request_id starting with
    'req_', api_request_timestamp ISO 8601}, response_type, and data.
    """
    res = api.create_organization(
        create_organization_payload(), platform_admin_headers,
    )
    body = res.json()
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "PRD §2.2: api_request_id must start with req_"
    )
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] in ("object", "array")
    assert "data" in body
    validate_success(res, expected_status=201)


def test_error_envelope_shape(api):
    """PRD §2.2: error body carries meta{api_request_id, api_request_timestamp},
    response_type 'error', and data{error_id, message}.
    """
    res = api.create_organization(create_organization_payload(), {})
    body = res.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == ApiErrorId.ERR_AUTH_REQUIRED.value
    assert isinstance(body["data"].get("message"), str)
    assert body["data"]["message"]
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def test_pagination_meta_present_on_list(api, platform_admin_headers):
    """PRD §2.3: "The response meta block carries limit, offset,
    total_count ..., and has_more."""
    org, _facility, _period = setup_org_facility_period()
    res = api.list_facilities(org["id"], platform_admin_headers)
    data, meta = validate_paginated(res)
    assert "limit" in meta and "offset" in meta
    assert "total_count" in meta and "has_more" in meta
    assert isinstance(data, list)


@pytest.mark.parametrize("limit", [0, 101, -1])
def test_pagination_limit_out_of_range_rejected(api, platform_admin_headers,
                                                limit):
    """PRD §2.3: "limit defaults to 10, has a minimum of 1, and a maximum
    of 100; values outside this range are rejected with
    ERR_VALIDATION_FAILED."""
    org, _facility, _period = setup_org_facility_period()
    res = api.list_facilities(
        org["id"], platform_admin_headers, params={"limit": limit},
    )
    validate_error(res, ApiErrorId.ERR_VALIDATION_FAILED.value)


# ---------------------------------------------------------------------------
# Path resolution (PRD §2.7)
# ---------------------------------------------------------------------------
def test_get_unknown_organization_returns_not_found(api,
                                                    platform_admin_headers):
    """PRD §2.7: "the server first checks the organization exists
    (returning ERR_NOT_FOUND if not) ..."""
    res = api.get_organization(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_facility_unknown_org_returns_not_found(api,
                                                       platform_admin_headers):
    """PRD §2.7: a missing top-level path resource returns ERR_NOT_FOUND
    before the body is even validated."""
    from test_helpers import create_facility_payload
    res = api.create_facility(
        NON_EXISTENT_UUID, create_facility_payload(), platform_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
