"""Tenant onboarding, package catalog, and subscription provisioning.

PRD §3.1, §3.2, §3.3, §3.6.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    PA, BO,
    assert_tenant,
    assert_package_version,
    assert_subscription,
    create_jurisdiction,
    create_jurisdiction_payload,
    create_package,
    create_package_payload,
    create_subscription_payload,
    create_tenant,
    create_tenant_payload,
    make_tenant_admin_headers,
    setup_active_subscription,
    setup_basic_monthly_package,
    setup_tenant_with_jurisdiction,
    validate_error,
    validate_success,
)


# ===========================================================================
# Tenant creation (PRD §3.2)
# ===========================================================================
class TestTenantCreation:

    def test_create_tenant_starts_in_trial(self, api):
        """PRD §3.2: 'The new tenant starts in tenant_status of TRIAL
        with restriction_level of NONE.'"""
        t = create_tenant()
        assert t["tenant_status"] == "TRIAL"
        assert t["restriction_level"] == "NONE"
        assert_tenant(t)

    def test_create_tenant_initial_outstanding_balance_is_zero(self, api):
        """PRD §3.11: 'outstanding_balance_cents is a computed field...
        It equals the sum of amount_due_cents for every Invoice owned by
        this tenant whose invoice_status is ISSUED, PARTIALLY_PAID, or
        OVERDUE.' A freshly-created tenant has no invoices."""
        t = create_tenant()
        assert t["outstanding_balance_cents"] == 0

    def test_subsidiary_with_missing_parent_id_rejected(self, api):
        """PRD §2.6: 'When billing_entity_type is SUBSIDIARY, the
        tenant must reference an existing parent via parent_tenant_id...
        otherwise the create request is rejected with
        ERR_INVALID_PARENT_TENANT (HTTP 422).'"""
        j = create_jurisdiction()
        res = api.create_tenant(
            create_tenant_payload(
                billing_entity_type="SUBSIDIARY",
                jurisdiction_code=j["jurisdiction_code"],
            ),
            PA,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PARENT_TENANT.value)

    def test_subsidiary_with_independent_parent_rejected(self, api):
        """PRD §2.6: 'the referenced tenant must itself have
        billing_entity_type of PARENT, or the create request is rejected
        with ERR_INVALID_PARENT_TENANT.'"""
        independent = create_tenant()  # INDEPENDENT by default
        j = create_jurisdiction()
        res = api.create_tenant(
            create_tenant_payload(
                billing_entity_type="SUBSIDIARY",
                parent_tenant_id=independent["id"],
                jurisdiction_code=j["jurisdiction_code"],
            ),
            PA,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PARENT_TENANT.value)

    def test_subsidiary_with_parent_succeeds(self, api):
        """PRD §2.6: 'the referenced tenant must itself have
        billing_entity_type of PARENT'."""
        j = create_jurisdiction()
        parent = create_tenant(
            jurisdiction_code=j["jurisdiction_code"],
            billing_entity_type="PARENT",
        )
        res = api.create_tenant(
            create_tenant_payload(
                billing_entity_type="SUBSIDIARY",
                parent_tenant_id=parent["id"],
                jurisdiction_code=j["jurisdiction_code"],
            ),
            PA,
        )
        data = validate_success(res, 201)
        assert data["billing_entity_type"] == "SUBSIDIARY"
        assert data["parent_tenant_id"] == parent["id"]


# ===========================================================================
# Package versioning (PRD §3.1)
# ===========================================================================
class TestPackageVersioning:

    def test_create_package_returns_immutable_shape(self, api):
        """PRD §3.1: 'PackageVersion is immutable once created; its
        resource representation carries only id, created_at, and the
        fields above — no updated_at, no version.'"""
        pkg = create_package()
        assert_package_version(pkg)
        assert "updated_at" not in pkg
        assert "version" not in pkg

    def test_duplicate_package_code_and_version_rejected(self, api):
        """PRD §3.1: 'the pair (package_code, version_number) is
        globally unique — a duplicate yields
        ERR_PACKAGE_VERSION_DUPLICATE.'"""
        pkg = create_package()
        # Resubmit same (package_code, version_number) — PRD pins this
        # as the uniqueness violation.
        res = api.create_package(
            create_package_payload(
                package_code=pkg["package_code"],
                version_number=pkg["version_number"],
            ),
            PA,
        )
        validate_error(res, ApiErrorId.ERR_PACKAGE_VERSION_DUPLICATE.value)


# ===========================================================================
# Subscription provisioning (PRD §3.3, §3.6)
# ===========================================================================
class TestSubscriptionProvisioning:

    def test_subscription_starts_in_trial(self, api):
        """PRD §3.3: 'persists the subscription with subscription_status
        of TRIAL and payment_status of CURRENT.'"""
        t, _j = setup_tenant_with_jurisdiction()
        pkg = setup_basic_monthly_package()
        res = api.create_subscription(
            t["id"],
            create_subscription_payload(package_code=pkg["package_code"]),
            make_tenant_admin_headers(t["id"]),
        )
        data = validate_success(res, 201)
        assert data["subscription_status"] == "TRIAL"
        assert data["payment_status"] == "CURRENT"
        assert_subscription(data)

    def test_subscription_currency_must_match_tenant(self, api):
        """PRD §3.6: 'a subscription is provisioned only when the
        resolved PackageVersion.currency equals the owning tenant's
        currency... mismatch yields ERR_CURRENCY_MISMATCH.'"""
        t, _j = setup_tenant_with_jurisdiction(currency="USD")
        pkg_eur = setup_basic_monthly_package(currency="EUR")
        res = api.create_subscription(
            t["id"],
            create_subscription_payload(package_code=pkg_eur["package_code"]),
            make_tenant_admin_headers(t["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CURRENCY_MISMATCH.value)

    def test_subscription_on_active_tenant_rejected(self, api):
        """PRD §3.3: 'attempting to create a subscription on a tenant
        whose status is anything other than TRIAL yields
        ERR_TENANT_STATUS_INVALID.'"""
        t, _pkg, _sub = setup_active_subscription()
        # Tenant is now ACTIVE; second subscription should be rejected
        # because tenant_status != TRIAL.
        pkg2 = setup_basic_monthly_package()
        res = api.create_subscription(
            t["id"],
            create_subscription_payload(package_code=pkg2["package_code"]),
            make_tenant_admin_headers(t["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TENANT_STATUS_INVALID.value)


# ===========================================================================
# Trial conversion (PRD §3.3)
# ===========================================================================
class TestTrialConversion:

    def test_conversion_advances_subscription_to_active(self, api):
        """PRD §3.3: 'Trial conversion advances the subscription from
        TRIAL to ACTIVE.'"""
        t, _pkg, sub_active = setup_active_subscription()
        assert sub_active["subscription_status"] == "ACTIVE"

    def test_conversion_cascades_tenant_to_active(self, api):
        """PRD §3.3: 'It cascades the tenant from TRIAL to ACTIVE if the
        tenant was still in TRIAL.'"""
        t, _pkg, _sub_active = setup_active_subscription()
        # Re-read the tenant
        res = api.get_tenant(t["id"], PA)
        data = validate_success(res, 200)
        assert data["tenant_status"] == "ACTIVE"

    def test_conversion_issues_prepaid_invoice(self, api):
        """PRD §3.3: 'issues a PREPAID Invoice when the resolved
        package's pricing_model is PREPAID or HYBRID.'"""
        from test_helpers import list_invoices
        t, _pkg, sub = setup_active_subscription(
            pricing_model="PREPAID", base_price_cents=3000,
        )
        invoices = list_invoices(t)
        # PRD §3.3: 'issues a PREPAID Invoice when the resolved
        # package's pricing_model is PREPAID or HYBRID.' The issuance
        # is auto-issued (not DRAFT) per PRD §3.9: 'or by the system
        # automatically at... trial conversion.'
        prepaid_issued = [
            i for i in invoices
            if i.get("subscription_id") == sub["id"]
            and i.get("pricing_model") == "PREPAID"
            and i.get("invoice_status") in ("ISSUED",)
        ]
        assert prepaid_issued, (
            f"Expected an ISSUED PREPAID invoice after trial conversion, "
            f"got {[(i['invoice_status'], i.get('pricing_model')) for i in invoices]}"
        )
