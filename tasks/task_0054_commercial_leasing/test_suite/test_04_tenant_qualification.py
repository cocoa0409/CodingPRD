"""Tenant onboarding, approval, rejection, and revocation.

PRD §3.2.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_tenant,
    create_approved_tenant,
    create_tenant,
    create_tenant_payload,
    setup_active_lease,
    setup_terminating_lease,
    unique_license,
    validate_error,
    validate_success,
    LA,
)


# ===========================================================================
# Tenant creation
# ===========================================================================
class TestTenantCreation:
    """PRD §3.2: 'A LeasingAgent records prospective tenants by
    supplying their legal_name, their business_license_no ... their
    license_expires_on date, and a contact_email ... A newly recorded
    tenant starts with qualification_status PENDING_REVIEW.'
    """

    def test_create_tenant_starts_pending_review(self, api):
        """PRD §3.2: 'A newly recorded tenant starts with
        qualification_status PENDING_REVIEW.'"""
        res = api.create_tenant(create_tenant_payload(), LA)
        data = validate_success(res, expected_status=201)
        assert_tenant(data)
        assert data["qualification_status"] == "PENDING_REVIEW"
        # PRD §2.9: aggregates initialise to zero.
        assert data["total_deposit_paid_cents"] == 0
        assert data["total_deposit_refunded_cents"] == 0
        assert data["total_deposit_retained_cents"] == 0


# ===========================================================================
# Tenant approval
# ===========================================================================
class TestTenantApproval:
    """PRD §3.2: 'The leasing agent then either approves the tenant
    (transitioning qualification_status from PENDING_REVIEW to
    APPROVED) or rejects it.'
    """

    def test_approve_pending_tenant(self, api):
        """PRD §3.2: 'transitioning qualification_status from
        PENDING_REVIEW to APPROVED'."""
        t = create_tenant()
        res = api.approve_tenant(t["id"], LA)
        data = validate_success(res)
        assert data["qualification_status"] == "APPROVED"

    def test_approve_expired_license_rejected(self, api):
        """PRD §3.2: 'Approval is rejected with ERR_LICENSE_EXPIRED if
        license_expires_on is on or before the current server date —
        that is, if the license has not strictly outlasted today.'"""
        # Use a license already expired.
        t = create_tenant(
            license_expires_on="2000-01-01T00:00:00.000Z",
        )
        res = api.approve_tenant(t["id"], LA)
        validate_error(res, ApiErrorId.ERR_LICENSE_EXPIRED.value)

    def test_approve_duplicate_license_rejected(self, api):
        """PRD §3.2: 'with ERR_DUPLICATE_LICENSE if any other tenant
        whose qualification_status is not REJECTED already carries the
        same business_license_no.'"""
        shared = unique_license()
        t1 = create_tenant(business_license_no=shared)
        # Approve t1 — succeeds.
        api.approve_tenant(t1["id"], LA)
        # Create second with same license.
        t2 = create_tenant(business_license_no=shared)
        res = api.approve_tenant(t2["id"], LA)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_LICENSE.value)

    def test_reject_pending_tenant(self, api):
        """PRD §3.2: 'or rejects it (transitioning to REJECTED, which is
        terminal).'"""
        t = create_tenant()
        res = api.reject_tenant(t["id"], LA)
        data = validate_success(res)
        assert data["qualification_status"] == "REJECTED"


# ===========================================================================
# Approval revocation
# ===========================================================================
class TestApprovalRevocation:
    """PRD §3.2: 'Approval may also be revoked by a leasing agent,
    returning the tenant to PENDING_REVIEW; revocation is blocked with
    ERR_TENANT_HAS_ACTIVE_LEASE if the tenant currently holds any Lease
    whose status is DRAFT, SIGNED, ACTIVE, AMENDMENT_PENDING, or
    TERMINATING.'
    """

    def test_revoke_approval_returns_to_pending_review(self, api):
        """PRD §3.2: 'returning the tenant to PENDING_REVIEW'."""
        t = create_approved_tenant()
        res = api.revoke_tenant_approval(t["id"], LA)
        data = validate_success(res)
        assert data["qualification_status"] == "PENDING_REVIEW"

    def test_revoke_blocked_by_active_lease(self, api):
        """PRD §3.2: 'revocation is blocked with
        ERR_TENANT_HAS_ACTIVE_LEASE if the tenant currently holds any
        Lease whose status is DRAFT, SIGNED, ACTIVE, AMENDMENT_PENDING,
        or TERMINATING.'"""
        ctx = setup_active_lease()
        res = api.revoke_tenant_approval(ctx["tenant"]["id"], LA)
        validate_error(res, ApiErrorId.ERR_TENANT_HAS_ACTIVE_LEASE.value)

    def test_revoke_blocked_by_terminating_lease(self, api):
        """PRD §3.2: 'revocation is blocked with
        ERR_TENANT_HAS_ACTIVE_LEASE if the tenant currently holds any
        Lease whose status is DRAFT, SIGNED, ACTIVE, AMENDMENT_PENDING,
        or TERMINATING.'"""
        ctx = setup_terminating_lease()
        res = api.revoke_tenant_approval(ctx["tenant"]["id"], LA)
        validate_error(res, ApiErrorId.ERR_TENANT_HAS_ACTIVE_LEASE.value)
