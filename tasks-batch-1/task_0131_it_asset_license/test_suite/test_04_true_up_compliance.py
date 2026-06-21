"""True-up reconciliation: live-vs-audit position divergence, the empty-install
zero-count boundary, and the verdict/finding produced at finalize.
"""
from test_helpers import (
    validate_success, TEST_USERS,
    set_clock, create_vendor, create_hardware,
    setup_product_with_active_entitlement, create_active_install,
    create_pending_install, create_true_up,
)

MGR = TEST_USERS["asset_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ─── dual_variant_calc / trueup_live_vs_audit_position_divergence ───

def _product_with_4_active_2_pending():
    """PER_SEAT product, ACTIVE entitlement entitled=5, 4 ACTIVE + 2 PENDING
    installs, all as_of 2025-03-01. Returns (product, entitlement, asset)."""
    set_clock("2025-03-01T00:00:00.000Z")
    vendor, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=5,
        grace_days=10,
    )
    asset = create_hardware(vendor["id"], asset_tag="TAG-SW", category="DESKTOP")
    for _ in range(4):
        create_active_install(product["id"], asset["id"], entitlement["id"])
    for _ in range(2):
        create_pending_install(product["id"], asset["id"], entitlement["id"])
    return product, entitlement, asset


def test_trueup_live_position_excludes_pending_installs(api):
    """PRD 3.7: "The installs in scope under the live variant are those whose
    `status` is `ACTIVE`." PRD 3.7: "The `verdict` is `OVER_DEPLOYED` when the
    position is strictly less than zero, and `COMPLIANT` otherwise — a position
    of exactly zero is compliant, not over-deployed."

    Design: Difficulty/dual_variant_calc/trueup_live_vs_audit_position_divergence
    """
    product, entitlement, asset = _product_with_4_active_2_pending()
    tu = create_true_up(product["id"], variant="LIVE", as_of="2025-03-01T00:00:00.000Z")
    finalized = validate_success(api.finalize_true_up(tu["id"], CO))
    # LIVE: entitled 5 - 4 ACTIVE consumed = +1 → COMPLIANT.
    assert finalized["position_units"] == 1
    assert finalized["verdict"] == "COMPLIANT"


def test_trueup_audit_position_includes_pending_installs(api):
    """PRD 3.7: "The installs in scope under the audit variant are those whose
    `status` is `ACTIVE` *or* `PENDING`, because in-flight installs are reserved
    against the pool for audit purposes." PRD 3.7: "The `verdict` is
    `OVER_DEPLOYED` when the position is strictly less than zero".

    Design: Difficulty/dual_variant_calc/trueup_live_vs_audit_position_divergence
    """
    product, entitlement, asset = _product_with_4_active_2_pending()
    tu = create_true_up(product["id"], variant="AUDIT", as_of="2025-03-01T00:00:00.000Z")
    finalized = validate_success(api.finalize_true_up(tu["id"], CO))
    # AUDIT: entitled 5 - (4 ACTIVE + 2 PENDING) consumed = -1 → OVER_DEPLOYED.
    assert finalized["position_units"] == -1
    assert finalized["verdict"] == "OVER_DEPLOYED"


# ─── boundary_precision_check / trueup_empty_install_set_zero_count ───

def _product_with_active_entitlement_no_installs():
    set_clock("2025-03-01T00:00:00.000Z")
    vendor, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=5,
    )
    return product, entitlement


def test_trueup_empty_install_set_consumed_is_zero(api):
    """PRD 3.7: "the `total_consumed_units` is the sum of `required_core_units`
    over the in-scope installs; and the `position_units` is the total entitled
    minus the total consumed."

    Design: Difficulty/boundary_precision_check/trueup_empty_install_set_zero_count
    """
    product, entitlement = _product_with_active_entitlement_no_installs()
    tu = create_true_up(product["id"], variant="LIVE", as_of="2025-03-01T00:00:00.000Z")
    finalized = validate_success(api.finalize_true_up(tu["id"], CO))
    assert finalized["total_consumed_units"] == 0


def test_trueup_empty_install_set_position_and_verdict(api):
    """PRD 3.7: "The `total_entitled_units` is the sum of `entitled_units` over
    the in-scope entitlements". PRD 3.7: "The `verdict` is `OVER_DEPLOYED` when
    the position is strictly less than zero, and `COMPLIANT` otherwise — a
    position of exactly zero is compliant, not over-deployed."

    Design: Difficulty/boundary_precision_check/trueup_empty_install_set_zero_count
    """
    product, entitlement = _product_with_active_entitlement_no_installs()
    tu = create_true_up(product["id"], variant="LIVE", as_of="2025-03-01T00:00:00.000Z")
    finalized = validate_success(api.finalize_true_up(tu["id"], CO))
    # entitled 5 - 0 consumed = 5 → COMPLIANT.
    assert finalized["position_units"] == 5
    assert finalized["verdict"] == "COMPLIANT"
