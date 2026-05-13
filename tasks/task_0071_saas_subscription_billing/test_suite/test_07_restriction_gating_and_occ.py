"""Restriction gating during dunning, OCC (version-conflict).

PRD §2.5, §2.12.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    PA,
    advance_clock,
    create_payment_payload,
    get_subscription,
    get_tenant,
    list_invoices,
    make_tenant_admin_headers,
    pay_invoice,
    run_dunning,
    setup_active_subscription,
    setup_overdue_due_to_dunning_run,
    setup_overdue_tier3_suspended,
    setup_unpaid_invoice_at_due_date,
    setup_upgrade_ladder,
    upgrade_subscription_payload,
    update_tenant_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Restriction gating (PRD §2.12)
# ===========================================================================
class TestRestrictionGating:

    def test_read_only_blocks_upgrade(self, api):
        """PRD §2.12: 'all POST, PATCH, and DELETE requests scoped to
        the tenant — except the payment endpoint, which must always
        remain available so the tenant can clear its debt — are rejected
        with ERR_TENANT_READ_ONLY while restriction_level is either
        READ_ONLY or FEATURE_RESTRICTED.'"""
        tenant, sub, _invoice = setup_overdue_due_to_dunning_run(
            base_price_cents=10_000,
            extra_seconds_past_due=45 * 86400,
        )
        t_after = get_tenant(tenant["id"])
        assert t_after["restriction_level"] in (
            "READ_ONLY", "FEATURE_RESTRICTED",
        ), (
            f"PRD §3.12: dunning past tier-one grace must raise "
            f"restriction_level; got {t_after['restriction_level']}"
        )
        res = api.upgrade_subscription(
            tenant["id"], sub["id"],
            upgrade_subscription_payload(target_package_code="X"),
            make_tenant_admin_headers(tenant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TENANT_READ_ONLY.value)

    def test_payments_remain_allowed_under_read_only(self, api):
        """PRD §2.12: '...except the payment endpoint, which must always
        remain available so the tenant can clear its debt.'"""
        tenant, sub, invoice = setup_overdue_due_to_dunning_run(
            base_price_cents=10_000,
            extra_seconds_past_due=15 * 86400,
        )
        # Refresh invoice to see its current late_fee_cents
        from test_helpers import get_invoice
        inv = get_invoice(tenant, invoice["id"])
        # Payment endpoint must still work despite READ_ONLY restriction.
        res = api.create_payment(
            tenant["id"], invoice["id"],
            create_payment_payload(
                amount_cents=inv["total_cents"] + inv["late_fee_cents"],
                currency=inv["currency"],
            ),
            make_tenant_admin_headers(tenant["id"]),
        )
        validate_success(res, 201)


# ===========================================================================
# OCC version conflict (PRD §2.5)
# ===========================================================================
class TestOptimisticConcurrency:

    def test_mismatched_version_on_patch_rejected(self, api):
        """PRD §2.5: 'When supplied, it is compared against the server's
        currently stored version; a mismatch is rejected with
        ERR_VERSION_CONFLICT (HTTP 409).'"""
        tenant, _pkg, sub = setup_active_subscription()
        # Subscription.version is at least 1 after activation; supply a
        # nonsense version and attempt an upgrade.
        # We don't have a second package handy in this setup, so use the
        # ladder helper for that test.
        tenant2, _pkg_low, pkg_high, sub_active = setup_upgrade_ladder()
        bad_version = sub_active.get("version", 1) + 99
        res = api.upgrade_subscription(
            tenant2["id"], sub_active["id"],
            upgrade_subscription_payload(
                target_package_code=pkg_high["package_code"],
                version=bad_version,
            ),
            make_tenant_admin_headers(tenant2["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_matching_version_succeeds(self, api):
        """PRD §2.5: 'On a successful mutation, version is incremented
        by 1 and updated_at is refreshed.'"""
        tenant, _pkg_low, pkg_high, sub_active = setup_upgrade_ladder()
        right_version = sub_active["version"]
        res = api.upgrade_subscription(
            tenant["id"], sub_active["id"],
            upgrade_subscription_payload(
                target_package_code=pkg_high["package_code"],
                version=right_version,
            ),
            make_tenant_admin_headers(tenant["id"]),
        )
        data = validate_success(res, 200)
        assert data["version"] == right_version + 1, (
            f"PRD §2.5: version must increment by exactly 1; "
            f"before={right_version}, after={data['version']}"
        )


# ===========================================================================
# Tenant termination preconditions (PRD §3.2)
# ===========================================================================
class TestTenantTermination:

    def test_terminate_active_with_outstanding_balance_rejected(self, api):
        """PRD §3.2: 'a PlatformAdmin may delete an ACTIVE tenant
        directly — but only when its computed outstanding_balance_cents
        equals zero (otherwise the request is rejected with
        ERR_OUTSTANDING_BALANCE_EXISTS).'"""
        tenant, _sub, _invoice = setup_unpaid_invoice_at_due_date(
            base_price_cents=5000,
        )
        # Tenant is now ACTIVE (after trial conversion) with an unpaid
        # invoice — outstanding_balance_cents > 0.
        res = api.delete_tenant(tenant["id"], PA)
        validate_error(res, ApiErrorId.ERR_OUTSTANDING_BALANCE_EXISTS.value)

    def test_terminate_parent_with_subsidiaries_rejected(self, api):
        """PRD §3.2: 'if the tenant's billing_entity_type is PARENT,
        when no subsidiary tenants remain attached (otherwise
        ERR_TENANT_HAS_SUBSIDIARIES).'

        Per PRD §2.11, state preconditions (state of the tenant) are
        checked before business constraints; PRD §3.2 says delete is only
        permitted on an ACTIVE tenant. We therefore transition the parent
        from TRIAL → ACTIVE by provisioning + converting a subscription
        before invoking delete, so the subsidiaries check (priority 10)
        is the first failing rule and surfaces ERR_TENANT_HAS_SUBSIDIARIES.
        """
        from test_helpers import (
            create_jurisdiction, create_tenant_payload, create_tenant,
            setup_basic_monthly_package, create_subscription,
            convert_subscription, get_invoice, pay_invoice,
            list_invoices,
        )
        from test_helpers import unique_external_reference
        j = create_jurisdiction()
        parent = create_tenant(
            jurisdiction_code=j["jurisdiction_code"],
            billing_entity_type="PARENT",
        )
        # Provision + convert a subscription so the parent reaches ACTIVE.
        pkg = setup_basic_monthly_package(base_price_cents=1000)
        sub_t = create_subscription(parent, package_code=pkg["package_code"])
        convert_subscription(parent, sub_t)
        # The prepaid invoice issued at conversion must be cleared so the
        # outstanding-balance precondition (priority 10, also a business
        # constraint) does not pre-empt the subsidiaries check. Per PRD
        # §2.11 priority 10, both ERR_OUTSTANDING_BALANCE_EXISTS and
        # ERR_TENANT_HAS_SUBSIDIARIES live at the same priority — PRD §3.2
        # presents them in the same clause connected by 'and'. We zero out
        # the balance so the only remaining failing check is subsidiaries.
        invs = list_invoices(parent)
        issued = [i for i in invs if i["invoice_status"] == "ISSUED"]
        for inv in issued:
            inv_full = get_invoice(parent, inv["id"])
            pay_invoice(parent, inv["id"],
                        amount_cents=inv_full["total_cents"],
                        external_reference=unique_external_reference())
        # Subsidiary attached
        sub_res = api.create_tenant(
            create_tenant_payload(
                billing_entity_type="SUBSIDIARY",
                parent_tenant_id=parent["id"],
                jurisdiction_code=j["jurisdiction_code"],
            ),
            PA,
        )
        validate_success(sub_res, 201)
        # Now try to terminate the parent
        res = api.delete_tenant(parent["id"], PA)
        validate_error(res, ApiErrorId.ERR_TENANT_HAS_SUBSIDIARIES.value)
