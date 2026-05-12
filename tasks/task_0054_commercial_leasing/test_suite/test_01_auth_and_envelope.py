"""Auth headers, role enforcement, response envelope, pagination,
left-to-right path resolution.

PRD §2.1, §2.2, §2.3, §2.7, §2.10 priorities 1–4.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_building,
    create_building_payload,
    create_tenant_payload,
    create_unit,
    setup_active_lease,
    setup_building_with_unit,
    create_approved_tenant,
    make_tenant_headers,
    validate_error,
    validate_paginated,
    validate_success,
    PM, LA, FO,
)


# ===========================================================================
# Auth header presence (PRD §2.1, validation priority 1)
# ===========================================================================
class TestAuthHeadersRequired:
    """PRD §2.1: 'Every request must carry two mandatory headers:
    X-User-ID, identifying the acting principal, and X-User-Role,
    identifying that principal's role. Requests missing either header,
    or carrying an unrecognized role, are rejected with
    ERR_UNAUTHENTICATED.'
    """

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: 'Requests missing either header ... are rejected
        with ERR_UNAUTHENTICATED.'"""
        res = api.create_building(create_building_payload(), {})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'Requests missing either header ... are rejected
        with ERR_UNAUTHENTICATED.'"""
        res = api.create_building(
            create_building_payload(),
            {"X-User-Role": "PropertyManager"},
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: 'Requests missing either header ... are rejected
        with ERR_UNAUTHENTICATED.'"""
        res = api.create_building(
            create_building_payload(),
            {"X-User-ID": "some-id"},
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_unrecognized_role_rejected(self, api):
        """PRD §2.1: 'Requests ... carrying an unrecognized role, are
        rejected with ERR_UNAUTHENTICATED.'"""
        res = api.create_building(
            create_building_payload(),
            {"X-User-ID": "ghost", "X-User-Role": "Sysadmin"},
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Role authorization (PRD §2.1, validation priority 2)
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: 'Requests whose role is not permitted for the targeted
    endpoint are rejected with ERR_FORBIDDEN.'
    """

    def test_leasing_agent_cannot_create_building(self, api):
        """PRD §4: 'POST /buildings — Create a building — PropertyManager'.
        PRD §2.1: 'are rejected with ERR_FORBIDDEN.'"""
        res = api.create_building(create_building_payload(), LA)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_tenant_cannot_create_tenant(self, api):
        """PRD §4: 'POST /tenants — Onboard a prospective tenant —
        LeasingAgent'."""
        res = api.create_tenant(
            create_tenant_payload(),
            TEST_USERS["tenant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_property_manager_cannot_sign_lease(self, api):
        """PRD §4: 'POST /leases/:lease_id/sign — LeasingAgent'."""
        res = api.sign_lease(NON_EXISTENT_UUID, PM)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_leasing_agent_cannot_amend_confirm(self, api):
        """PRD §4: 'POST /leases/:lease_id/amend-confirm — FinanceOfficer'."""
        res = api.amend_confirm_lease(NON_EXISTENT_UUID, LA)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_tenant_cannot_finalize_move_out(self, api):
        """PRD §4: 'POST /move-out-requests/:request_id/finalize —
        FinanceOfficer'."""
        res = api.finalize_move_out(
            NON_EXISTENT_UUID, TEST_USERS["tenant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_finance_officer_cannot_create_unit(self, api):
        """PRD §4: 'POST /buildings/:building_id/units — Create a unit
        inside a building — PropertyManager'."""
        building = create_building()
        from test_helpers import create_unit_payload
        res = api.create_unit(building["id"], create_unit_payload(), FO)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Tenant ownership guard (PRD §2.1)
# ===========================================================================
class TestTenantOwnershipGuard:
    """PRD §2.1: 'When X-User-Role is Tenant, X-User-ID is the id of
    the acting Tenant; ownership checks on any resource that references
    a Tenant — a Lease, a Deposit, a FeeBill, a MoveOutRequest, or a
    Unit reached through one of those — compare the resource's tenant
    foreign-key field to X-User-ID, and a tenant acting on a resource
    that belongs to another tenant is rejected with ERR_FORBIDDEN.'
    """

    def test_top_up_by_wrong_tenant_rejected(self, api):
        """PRD §2.1: 'a tenant acting on a resource that belongs to
        another tenant is rejected with ERR_FORBIDDEN.'"""
        ctx = setup_active_lease()
        other = create_approved_tenant()
        res = api.top_up_deposit(
            ctx["deposit"]["id"],
            {"amount_cents": 0},
            make_tenant_headers(other["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_move_out_by_wrong_tenant_rejected(self, api):
        """PRD §2.1: 'a tenant acting on a resource that belongs to
        another tenant is rejected with ERR_FORBIDDEN.'"""
        ctx = setup_active_lease()
        other = create_approved_tenant()
        res = api.move_out_request(
            ctx["lease"]["id"],
            {"target_move_out_date": "2099-01-01T00:00:00.000Z"},
            make_tenant_headers(other["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Path resource existence (PRD §2.7, validation priority 3)
# ===========================================================================
class TestNotFound:
    """PRD §2.7: 'The server validates these identifiers strictly
    left-to-right. The first segment whose value does not resolve to a
    stored row causes the request to fail immediately with
    ERR_NOT_FOUND.'
    """

    def test_get_nonexistent_building(self, api):
        res = api.get_building(NON_EXISTENT_UUID, PM)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_tenant(self, api):
        res = api.get_tenant(NON_EXISTENT_UUID, LA)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_lease(self, api):
        res = api.get_lease(NON_EXISTENT_UUID, LA)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_deposit(self, api):
        res = api.get_deposit(NON_EXISTENT_UUID, LA)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_fee_bill(self, api):
        res = api.get_fee_bill(NON_EXISTENT_UUID, FO)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_move_out_request(self, api):
        res = api.get_move_out_request(NON_EXISTENT_UUID, FO)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


class TestLeftToRightPathResolution:
    """PRD §2.7: 'The server validates these identifiers strictly
    left-to-right. The first segment whose value does not resolve to a
    stored row causes the request to fail immediately with
    ERR_NOT_FOUND; subsequent segments are not consulted.'
    """

    def test_unit_under_unknown_building(self, api):
        res = api.get_unit(NON_EXISTENT_UUID, NON_EXISTENT_UUID, PM)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_unit_under_real_building_but_unknown_unit_id(self, api):
        building = create_building()
        res = api.get_unit(building["id"], NON_EXISTENT_UUID, PM)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_child_belongs_to_wrong_parent(self, api):
        """PRD §2.7: 'If every segment resolves but a child does not
        belong to its declared parent ... the request likewise fails
        with ERR_NOT_FOUND.'"""
        building_a, unit_a = setup_building_with_unit()
        building_b = create_building()
        res = api.get_unit(building_b["id"], unit_a["id"], PM)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Success-envelope and pagination (PRD §2.2, §2.3)
# ===========================================================================
class TestEnvelopeAndPagination:
    """PRD §2.2 / §2.3."""

    def test_success_envelope_shape(self, api):
        """PRD §2.2: 'All successful API responses ... follow this
        standard envelope format ... meta ... response_type ... data'."""
        res = api.create_building(create_building_payload(), PM)
        body = res.json()
        assert "meta" in body
        assert "response_type" in body
        assert "data" in body
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"]
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"api_request_id must start with req_, got "
            f"{body['meta']['api_request_id']!r}"
        )
        assert "api_request_timestamp" in body["meta"]

    def test_error_envelope_shape(self, api):
        """PRD §2.2: error envelope shape with error_id + message."""
        res = api.create_building(create_building_payload(), {})
        body = res.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]
        assert body["data"]["error_id"] == ApiErrorId.ERR_UNAUTHENTICATED.value

    def test_audit_event_listing_pagination_defaults(self, api):
        """PRD §2.3: 'The limit parameter caps the number of returned
        resources; it defaults to 10 ... The offset parameter ...
        defaults to 0. ... Every list response includes limit, offset,
        total_count, and has_more inside the meta object.'"""
        res = api.list_audit_events(PM)
        rows, meta = validate_paginated(res)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert "total_count" in meta
        assert "has_more" in meta

    def test_audit_event_listing_limit_honored(self, api):
        """PRD §2.3: 'The limit parameter caps the number of returned
        resources; it defaults to 10, is bounded by a minimum of 1, and
        by a maximum of 100.'"""
        # create some traffic
        create_building()
        create_building()
        res = api.list_audit_events(PM, params={"limit": 1})
        rows, meta = validate_paginated(res)
        assert meta["limit"] == 1
        assert len(rows) <= 1
