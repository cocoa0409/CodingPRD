"""Tenant and Member CRUD + creation-time invariants.

Covers PRD §3.1 (tenant creation with default credit limit, member uniqueness and
tenant-existence requirements).
"""

import pytest

from test_helpers import (
    TEST_USERS,
    THRESHOLDS,
    assert_member,
    assert_tenant,
    create_member_payload,
    create_tenant,
    create_tenant_payload,
    validate_error,
    validate_success,
)


def test_create_tenant_with_defaults(api, admin_headers):
    """PRD §3.1: "The credit limit defaults to 500,000 cents (that is, 5,000
    dollars expressed in cents) and must be zero or positive. The new tenant is
    created with `status` of `ACTIVE`, `access_posture` of `OPEN`, and
    `outstanding_balance_cents` of 0."

    Claim: POST /tenants with only legal_name sets credit_limit_cents=500_000,
    access_posture=OPEN, status=ACTIVE, outstanding_balance_cents=0.
    """
    res = api.create_tenant({"legal_name": "Default Tenant"}, admin_headers)
    tenant = validate_success(res, expected_status=201)
    assert_tenant(tenant)
    assert tenant["legal_name"] == "Default Tenant"
    assert tenant["credit_limit_cents"] == 500_000
    assert tenant["access_posture"] == "OPEN"
    assert tenant["status"] == "ACTIVE"
    assert tenant["outstanding_balance_cents"] == 0
    assert tenant["version"] == 1


def test_create_tenant_with_custom_credit_limit(api, admin_headers):
    """PRD §3.1: "an optional `credit_limit_cents`. The credit `limit` defaults to
    500,000 cents (that is, 5,000 dollars expressed in cents) and must be zero
    or positive."

    Claim: supplying credit_limit_cents overrides the default.
    """
    res = api.create_tenant(
        {"legal_name": "Custom Credit", "credit_limit_cents": 100_000}, admin_headers
    )
    tenant = validate_success(res, expected_status=201)
    assert tenant["credit_limit_cents"] == 100_000


def test_get_nonexistent_tenant_returns_not_found(api, admin_headers):
    """PRD §2.7: "if the tenant does not exist the response is `ERR_NOT_FOUND`."

    Claim: GET /tenants/{random-uuid} → ERR_NOT_FOUND (404).
    """
    res = api.get_tenant("00000000-0000-4000-8000-000000000000", admin_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_member_under_active_tenant(api, admin_headers):
    """PRD §3.1: "Members are provisioned under a tenant by either a
    `PlatformAdmin` or a `TenantAdmin` of that tenant, supplying a `tenant_id`, an
    `email` (unique across every member in the system regardless of tenant), a
    `full_name`, and an optional `role_in_tenant` which may be either `ADMIN` or `STAFF`
    and defaults to `STAFF`."

    Claim: POST /members under an ACTIVE tenant returns a Member with status
    ACTIVE and default role_in_tenant=STAFF when omitted.
    """
    tenant = create_tenant()
    payload = create_member_payload(tenant["id"])
    res = api.create_member(payload, admin_headers)
    member = validate_success(res, expected_status=201)
    assert_member(member)
    assert member["tenant_id"] == tenant["id"]
    assert member["status"] == "ACTIVE"
    assert member["role_in_tenant"] == "STAFF"


def test_create_member_with_admin_role(api, admin_headers):
    """PRD §3.1: "`role_in_tenant` which may be either `ADMIN` or `STAFF` and defaults
    to `STAFF`."

    Claim: role_in_tenant=ADMIN is accepted and echoed back.
    """
    tenant = create_tenant()
    res = api.create_member(
        create_member_payload(tenant["id"], role_in_tenant="ADMIN"), admin_headers
    )
    member = validate_success(res, expected_status=201)
    assert member["role_in_tenant"] == "ADMIN"


def test_duplicate_member_email_rejected(api, admin_headers):
    """PRD §3.1: "an `email` (unique across every member in the system regardless
    of tenant)."

    Claim: POST /members with a reused email must be rejected. (The PRD pins
    uniqueness; the §5 error catalogue does not name a dedicated email-conflict
    error, so any 4xx rejection is faithful. We assert only that the second call
    does not succeed — no specific error_id is required by PRD.)
    """
    tenant_a = create_tenant()
    tenant_b = create_tenant()
    payload_a = create_member_payload(tenant_a["id"], email="dupe@example.com")
    validate_success(api.create_member(payload_a, admin_headers), expected_status=201)
    payload_b = create_member_payload(tenant_b["id"], email="dupe@example.com")
    res = api.create_member(payload_b, admin_headers)
    assert res.status_code >= 400 and res.status_code < 500, (
        "Second member with duplicate email must be rejected per PRD §3.1 email "
        "uniqueness"
    )


def test_create_member_with_nonexistent_tenant_returns_fk_error(api, admin_headers):
    """PRD §2.7: "Body-level foreign keys — `tenant_id`, `member_id`, `resource_id`,
    `host_member_id`, `bill_id` — are also resolved; if any one of them references a
    row that does not exist, the response is `ERR_REFERENCED_ENTITY_MISSING`."

    Claim: non-existent tenant_id in POST /members → ERR_REFERENCED_ENTITY_MISSING.
    """
    res = api.create_member(
        create_member_payload("00000000-0000-4000-8000-000000000000"), admin_headers
    )
    validate_error(res, "ERR_REFERENCED_ENTITY_MISSING", expected_status=404)
