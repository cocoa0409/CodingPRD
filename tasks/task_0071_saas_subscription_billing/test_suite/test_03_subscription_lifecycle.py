"""Subscription state machine, upgrade/downgrade, and cancellation.

PRD §3.3, §3.4.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    PA, BO,
    advance_clock,
    convert_subscription,
    create_subscription,
    create_tenant,
    downgrade_subscription,
    downgrade_subscription_payload,
    get_subscription,
    list_subscription_changes,
    list_invoices,
    list_credit_notes,
    make_tenant_admin_headers,
    setup_active_subscription,
    setup_basic_monthly_package,
    setup_tenant_with_jurisdiction,
    setup_upgrade_ladder,
    upgrade_subscription,
    upgrade_subscription_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Upgrade (PRD §3.4)
# ===========================================================================
class TestUpgrade:

    def test_upgrade_requires_strictly_higher_base_price(self, api):
        """PRD §3.4: 'the target PackageVersion.base_price_cents to be
        strictly greater than the current package's base_price_cents
        (otherwise ERR_NOT_AN_UPGRADE).'"""
        tenant, pkg_low, _pkg_high, sub_active = setup_upgrade_ladder(
            low_base_cents=3000, high_base_cents=6000,
        )
        # Attempt to "upgrade" to the same package (not strictly greater).
        res = api.upgrade_subscription(
            tenant["id"], sub_active["id"],
            upgrade_subscription_payload(
                target_package_code=pkg_low["package_code"],
            ),
            make_tenant_admin_headers(tenant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOT_AN_UPGRADE.value)

    def test_successful_upgrade_emits_subscription_change(self, api):
        """PRD §3.4: 'creates a SubscriptionChange entry with change_type
        of UPGRADE.'"""
        tenant, _pkg_low, pkg_high, sub_active = setup_upgrade_ladder()
        upgrade_subscription(tenant, sub_active,
                             target_package_code=pkg_high["package_code"])
        changes = list_subscription_changes(tenant, sub_active)
        upgrades = [c for c in changes if c["change_type"] == "UPGRADE"]
        assert upgrades, "Expected at least one UPGRADE SubscriptionChange"

    def test_successful_upgrade_replaces_package_version_id(self, api):
        """PRD §3.4: 'the system replaces package_version_id with the
        target's id.'"""
        tenant, _pkg_low, pkg_high, sub_active = setup_upgrade_ladder()
        upgrade_subscription(tenant, sub_active,
                             target_package_code=pkg_high["package_code"])
        sub_after = get_subscription(tenant, sub_active)
        assert sub_after["package_version_id"] == pkg_high["id"]


# ===========================================================================
# Downgrade (PRD §3.4)
# ===========================================================================
class TestDowngrade:

    def test_downgrade_requires_strictly_lower_base_price(self, api):
        """PRD §3.4: 'Downgrading also requires the subscription in
        ACTIVE and the target's base_price_cents to be strictly less
        than the current package's base_price_cents (otherwise
        ERR_NOT_A_DOWNGRADE).'"""
        tenant, _pkg_low, pkg_high, sub_active = setup_upgrade_ladder()
        # "downgrade" to the same package (current is pkg_low at 3000;
        # downgrade target must be strictly lower; pkg_high at 6000 is
        # not lower).
        res = api.downgrade_subscription(
            tenant["id"], sub_active["id"],
            downgrade_subscription_payload(
                target_package_code=pkg_high["package_code"],
                mode="END_OF_CYCLE",
            ),
            make_tenant_admin_headers(tenant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOT_A_DOWNGRADE.value)

    def test_downgrade_end_of_cycle_sets_pending_downgrade(self, api):
        """PRD §3.4: 'When mode is END_OF_CYCLE, the subscription moves
        to PENDING_DOWNGRADE, the system records the target on
        pending_change_package_version_id.'"""
        tenant, pkg_low, pkg_high, _sub_active = setup_upgrade_ladder()
        # Start on pkg_high so we can downgrade to pkg_low
        sub_hi = create_subscription(create_tenant(
            jurisdiction_code=None,
        ), package_code=pkg_high["package_code"])
        # That created another tenant; instead use a cleaner two-step:
        # First upgrade to pkg_high so the subscription is on the high
        # plan; then downgrade to pkg_low.
        tenant2, pkg_low2, pkg_high2, sub_active2 = setup_upgrade_ladder()
        upgrade_subscription(tenant2, sub_active2,
                             target_package_code=pkg_high2["package_code"])
        # Now downgrade to pkg_low2
        downgrade_subscription(
            tenant2, sub_active2,
            target_package_code=pkg_low2["package_code"],
            mode="END_OF_CYCLE",
        )
        sub_after = get_subscription(tenant2, sub_active2)
        assert sub_after["subscription_status"] == "PENDING_DOWNGRADE"
        assert sub_after["pending_change_package_version_id"] == pkg_low2["id"]


# ===========================================================================
# Cancellation (PRD §3.3)
# ===========================================================================
class TestCancellation:

    def test_cancel_active_subscription_transitions_to_cancelled(self, api):
        """PRD §3.3: 'From ACTIVE (or PENDING_DOWNGRADE), cancellation
        moves the subscription to CANCELLED.'"""
        tenant, _pkg, sub_active = setup_active_subscription()
        res = api.cancel_subscription(
            tenant["id"], sub_active["id"],
            make_tenant_admin_headers(tenant["id"]),
        )
        # PRD §4: "deletions that have no body return HTTP 204."
        assert res.status_code == 204, (
            f"Expected 204, got {res.status_code}: {res.text}"
        )
        sub_after = get_subscription(tenant, sub_active)
        assert sub_after["subscription_status"] == "CANCELLED"

    def test_cancel_trial_subscription_does_not_issue_invoice(self, api):
        """PRD §3.3: 'From TRIAL, cancellation moves the subscription
        directly to CANCELLED without issuing any invoice.'"""
        t, _j = setup_tenant_with_jurisdiction()
        pkg = setup_basic_monthly_package()
        sub_trial = create_subscription(t, package_code=pkg["package_code"])
        before_invoices = list_invoices(t)
        res = api.cancel_subscription(
            t["id"], sub_trial["id"],
            make_tenant_admin_headers(t["id"]),
        )
        # PRD §4: "deletions that have no body return HTTP 204."
        assert res.status_code == 204, (
            f"Expected 204, got {res.status_code}: {res.text}"
        )
        after_invoices = list_invoices(t)
        # No NEW invoice issued on TRIAL cancellation.
        assert len(after_invoices) == len(before_invoices), (
            "PRD §3.3: 'From TRIAL, cancellation moves the subscription "
            "directly to CANCELLED without issuing any invoice.'"
        )
