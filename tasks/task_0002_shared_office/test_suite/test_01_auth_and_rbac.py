"""Authentication and role-based access control tests.

Covers PRD §2.1 (headers, role identity) and §2.8 (validation ordering for
auth/role/RBAC errors).
"""

import pytest

from test_helpers import (
    TEST_USERS,
    build_user_headers,
    create_tenant_payload,
    validate_error,
)


def test_missing_x_user_id_header_rejected(api):
    """PRD §2.1: "Every request (except the health probe) must carry two headers:
    `X-User-ID` identifying the caller, and `X-User-Role` naming the caller's role.
    If either header is missing or empty, the request is rejected with
    `ERR_MISSING_AUTH`."

    Claim: missing X-User-ID on any non-health request → ERR_MISSING_AUTH (401).
    """
    headers = {"X-User-Role": "PlatformAdmin"}  # X-User-ID intentionally absent
    res = api.create_tenant(create_tenant_payload(), headers)
    validate_error(res, "ERR_MISSING_AUTH", expected_status=401)


def test_missing_x_user_role_header_rejected(api):
    """PRD §2.1: "Every request (except the health probe) must carry two headers:
    `X-User-ID` identifying the caller, and `X-User-Role` naming the caller's role.
    If either header is missing or empty, the request is rejected with
    `ERR_MISSING_AUTH`."

    Claim: missing X-User-Role on any non-health request → ERR_MISSING_AUTH (401).
    """
    headers = {"X-User-ID": "someone"}  # X-User-Role intentionally absent
    res = api.create_tenant(create_tenant_payload(), headers)
    validate_error(res, "ERR_MISSING_AUTH", expected_status=401)


def test_empty_x_user_id_rejected(api):
    """PRD §2.1: "If either header is missing or empty, the request is rejected
    with `ERR_MISSING_AUTH`."

    Claim: empty X-User-ID string → ERR_MISSING_AUTH (401).
    """
    headers = {"X-User-ID": "", "X-User-Role": "PlatformAdmin"}
    res = api.create_tenant(create_tenant_payload(), headers)
    validate_error(res, "ERR_MISSING_AUTH", expected_status=401)


def test_unknown_role_rejected(api):
    """PRD §2.1: "If `X-User-Role` carries a string that is not one of the declared
    roles, the request is rejected with `ERR_UNKNOWN_ROLE`."

    Claim: bogus role string → ERR_UNKNOWN_ROLE (401).
    """
    headers = build_user_headers("some-user", "GodMode")
    res = api.create_tenant(create_tenant_payload(), headers)
    validate_error(res, "ERR_UNKNOWN_ROLE", expected_status=401)


@pytest.mark.parametrize(
    "role",
    ["TenantAdmin", "TenantMember", "Receptionist", "BillingOfficer", "PaymentClerk"],
)
def test_non_platform_admin_cannot_create_tenant(api, role):
    """PRD §2.1: "If the role is recognized but not permitted to perform the
    requested operation per the RBAC matrix, the request is rejected with
    `ERR_FORBIDDEN`."

    Claim: only PlatformAdmin may POST /tenants per PRD §4 — other roles get
    ERR_FORBIDDEN (403).
    """
    headers = build_user_headers(f"test-{role}-rbac", role)
    res = api.create_tenant(create_tenant_payload(), headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_health_endpoint_does_not_require_auth(api):
    """PRD §2.1: "Every request (except the health probe) must carry two headers."

    Claim: GET /health is the explicit auth-exempt endpoint; calling it without
    headers must NOT fail with ERR_MISSING_AUTH.
    """
    res = api.health(headers={})
    # The runner's auto status check for ERR_MISSING_AUTH would fire 401; PRD exempts
    # this endpoint entirely, so any 2xx is acceptable and a 401 would violate the rule.
    assert res.status_code != 401, (
        "PRD §2.1 exempts the health probe from the auth-header requirement; a 401 "
        "indicates the exemption was not honored."
    )


def test_auth_error_precedes_existence_error(api):
    """PRD §2.8: "a single request that is both unauthenticated and touches a
    non-existent tenant must surface the auth error, not the existence error."

    Claim: with missing auth headers AND non-existent tenant id, server returns
    ERR_MISSING_AUTH (not ERR_NOT_FOUND).
    """
    fake_id = "00000000-0000-4000-8000-000000000000"
    res = api.get_tenant(fake_id, headers={})
    validate_error(res, "ERR_MISSING_AUTH", expected_status=401)
