"""CAM reconciliation and escalation calculations (depth queue A).

Covers the dual-variant true-up, the combinatorial reconciled-CAM with nested
min/branch, the per-line-item gross-up rounding order, and the fixed-pct vs CPI
escalation divergence. Every literal expected value is copied from the design
index, where it was pre-computed.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_example_b_reconciliation, post_reconciliation,
    create_property, create_tenant, create_active_lease, create_pool, add_line_item,
    create_in_review_reconciliation, get_reconciliation_version,
    PM_HEADERS, ACCT_HEADERS,
)


# ─── Rule 1: dual_variant_calc / cam_estimated_vs_reconciled_true_up ────────

def test_true_up_is_signed_difference_of_estimated_and_reconciled(api):
    """PRD §3.7: "The estimated CAM billed, estimated_cam_billed_cents, is twelve
    times the lease's estimated_cam_cents_monthly"
    PRD §3.7: "The true-up, true_up_cents, is reconciled_cam_cents minus
    estimated_cam_billed_cents"

    Design: Difficulty/dual_variant_calc/cam_estimated_vs_reconciled_true_up
    """
    ctx = setup_example_b_reconciliation()
    posted = post_reconciliation(ctx["recon"]["id"], ctx["recon_version"])
    assert posted["estimated_cam_billed_cents"] == 180000
    assert posted["reconciled_cam_cents"] == 250000
    assert posted["true_up_cents"] == 70000


def test_posted_reconciliation_snapshots_status_and_figures(api):
    """PRD §3.7: "These four computed values — pro_rata_share_pct,
    reconciled_cam_cents, estimated_cam_billed_cents, and true_up_cents — are
    snapshotted onto the reconciliation as it posts."

    Design: Difficulty/dual_variant_calc/cam_estimated_vs_reconciled_true_up
    """
    ctx = setup_example_b_reconciliation()
    posted = post_reconciliation(ctx["recon"]["id"], ctx["recon_version"])
    assert posted["status"] == "POSTED"
    refetched = validate_success(
        api.get_reconciliation(ctx["recon"]["id"], ACCT_HEADERS), 200)
    assert refetched["true_up_cents"] == 70000
    assert refetched["reconciled_cam_cents"] == 250000


# ─── Rule 1: dual_variant_calc / base_rent_fixed_pct_vs_cpi_escalation ──────

def test_fixed_pct_escalation_applies_flat_percent(api):
    """PRD §3.4: "When the type is FIXED_PCT, the new base is the current
    base_rent_cents_annual multiplied by one plus the lease's escalation_rate,
    rounded half-up to whole cents — a flat percentage increase regardless of any
    index."

    Design: Difficulty/dual_variant_calc/base_rent_fixed_pct_vs_cpi_escalation
    """
    prop = create_property(total_rentable_sqft=100000, name="Tower")
    tenant = create_tenant("F Co", "f@x.com")
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=10000000,
                                escalation_type="FIXED_PCT", escalation_rate=0.03)
    escalated = validate_success(api.escalate_lease(lease["id"], {}, PM_HEADERS), 200)
    assert escalated["base_rent_cents_annual"] == 10300000


def test_cpi_escalation_collared_at_escalation_rate(api):
    """PRD §3.4: "then a cap, so the applied increase is the smaller of the
    floored raw increase and the lease's escalation_rate, which serves as the CPI
    collar. The new base is the current base rent multiplied by one plus that
    applied increase, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/base_rent_fixed_pct_vs_cpi_escalation
    """
    prop = create_property(total_rentable_sqft=100000, name="Tower2")
    tenant = create_tenant("C Co", "c@x.com")
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=10000000,
                                escalation_type="CPI", escalation_rate=0.04,
                                cpi_base_index=250.0)
    # raw increase (262.5-250)/250 = 0.05, collared to 0.04 -> base * 1.04
    escalated = validate_success(
        api.escalate_lease(lease["id"], {"current_cpi_index": 262.5}, PM_HEADERS), 200)
    assert escalated["base_rent_cents_annual"] == 10400000


# ─── Rule 2: combinatorial_formula / reconciled_cam_nested_min_with_branches_mode_a ──

def test_reconciled_cam_with_binding_controllable_cap(api):
    """PRD §3.7: "the allowed capped amount is the smaller of the tenant's capped
    share and that ceiling. The cap binds only when the tenant's capped share
    strictly exceeds the ceiling"
    PRD §3.7: "The reconciled CAM, reconciled_cam_cents, is the sum of those two
    rounded portions — and the order is pinned: each tenant slice is rounded
    first, then the two are added, never summed and rounded once."

    Design: Difficulty/combinatorial_formula/reconciled_cam_nested_min_with_branches_mode_a
    """
    # share 0.5; capped slice 1000000 -> tenant_capped_share 500000, ceiling
    # 420000 -> allowed 420000; non-capped pool 400000 -> tenant_noncapped 200000;
    # reconciled = 620000.
    prop = create_property(total_rentable_sqft=10000, gross_up_occupancy_pct=0.95, name="Mall")
    filler = create_tenant("Filler Co", "fl@x.com")
    cap_tenant = create_tenant("Cap Co", "cap@x.com")
    create_active_lease(prop["id"], filler["id"], leased_sqft=4500, base_rent_cents_annual=0)
    cap_lease = create_active_lease(
        prop["id"], cap_tenant["id"], leased_sqft=5000, base_rent_cents_annual=0,
        controllable_cap_pct=0.05, prior_year_capped_base_cents=400000,
        estimated_cam_cents_monthly=40000)
    pool = create_pool(prop["id"], pool_year=2025,
                       pro_rata_denominator="TOTAL_RENTABLE", admin_fee_pct=0)
    add_line_item(pool["id"], "SECURITY", 1000000, "CAPPED_CONTROLLABLE", is_variable=True)
    add_line_item(pool["id"], "TAXES", 400000, "RECOVERABLE", is_variable=False)
    recon = create_in_review_reconciliation(cap_lease["id"], pool["id"], 2025)
    posted = post_reconciliation(recon["id"], recon["version"])
    assert posted["reconciled_cam_cents"] == 620000


def test_true_up_with_binding_controllable_cap(api):
    """PRD §3.7: "The true-up, true_up_cents, is reconciled_cam_cents minus
    estimated_cam_billed_cents"

    Design: Difficulty/combinatorial_formula/reconciled_cam_nested_min_with_branches_mode_a
    """
    # reconciled 620000, estimated 12*40000 = 480000 -> true_up 140000.
    prop = create_property(total_rentable_sqft=10000, gross_up_occupancy_pct=0.95, name="Mall2")
    filler = create_tenant("Filler2 Co", "fl2@x.com")
    cap_tenant = create_tenant("Cap2 Co", "cap2@x.com")
    create_active_lease(prop["id"], filler["id"], leased_sqft=4500, base_rent_cents_annual=0)
    cap_lease = create_active_lease(
        prop["id"], cap_tenant["id"], leased_sqft=5000, base_rent_cents_annual=0,
        controllable_cap_pct=0.05, prior_year_capped_base_cents=400000,
        estimated_cam_cents_monthly=40000)
    pool = create_pool(prop["id"], pool_year=2025,
                       pro_rata_denominator="TOTAL_RENTABLE", admin_fee_pct=0)
    add_line_item(pool["id"], "SECURITY", 1000000, "CAPPED_CONTROLLABLE", is_variable=True)
    add_line_item(pool["id"], "TAXES", 400000, "RECOVERABLE", is_variable=False)
    recon = create_in_review_reconciliation(cap_lease["id"], pool["id"], 2025)
    posted = post_reconciliation(recon["id"], recon["version"])
    assert posted["true_up_cents"] == 140000


# ─── Rule 2: combinatorial_formula / gross_up_round_per_item_then_sum_mode_b ──

def test_gross_up_rounds_each_variable_line_before_summing(api):
    """PRD §3.2: "For a variable item, its grossed amount is its amount_cents
    multiplied by the gross-up factor, rounded half-up to whole cents at that line
    item."
    PRD §3.2: "The order is pinned and load-bearing: each variable line is rounded
    before the items are summed, and the admin fee is rounded once on the
    completed sum."

    Design: Difficulty/combinatorial_formula/gross_up_round_per_item_then_sum_mode_b
    """
    # factor 0.95/0.8 = 1.1875; 500008->593760, 700008->831260, fixed 100000
    # -> round-per-item-then-sum total 1525020 (sum-then-round would be 1525019).
    prop = create_property(total_rentable_sqft=10000, gross_up_occupancy_pct=0.95, name="Center")
    tenant = create_tenant("Occ Co", "o@x.com")
    create_active_lease(prop["id"], tenant["id"], leased_sqft=8000, base_rent_cents_annual=0)
    pool = create_pool(prop["id"], pool_year=2025, admin_fee_pct=0)
    add_line_item(pool["id"], "LANDSCAPING", 500008, "RECOVERABLE", is_variable=True)
    add_line_item(pool["id"], "SNOW_REMOVAL", 700008, "RECOVERABLE", is_variable=True)
    add_line_item(pool["id"], "MANAGEMENT", 100000, "RECOVERABLE", is_variable=False)
    pool_after = validate_success(api.get_expense_pool(pool["id"], ACCT_HEADERS), 200)
    assert pool_after["total_recoverable_cents"] == 1525020


def test_gross_up_factor_scales_variable_cost_in_underoccupied_building(api):
    """PRD §3.2: "The gross-up factor is the pool property's gross_up_occupancy_pct
    divided by that actual occupancy; in an under-occupied building this factor
    exceeds one, scaling variable costs up so the landlord recovers full variable
    cost despite vacancy."

    Design: Difficulty/combinatorial_formula/gross_up_round_per_item_then_sum_mode_b
    """
    # The grossed total (1525020) strictly exceeds the raw sum (1300016) because
    # the under-occupancy factor > 1 scales the two variable lines up.
    prop = create_property(total_rentable_sqft=10000, gross_up_occupancy_pct=0.95, name="Center2")
    tenant = create_tenant("Occ2 Co", "o2@x.com")
    create_active_lease(prop["id"], tenant["id"], leased_sqft=8000, base_rent_cents_annual=0)
    pool = create_pool(prop["id"], pool_year=2025, admin_fee_pct=0)
    add_line_item(pool["id"], "LANDSCAPING", 500008, "RECOVERABLE", is_variable=True)
    add_line_item(pool["id"], "SNOW_REMOVAL", 700008, "RECOVERABLE", is_variable=True)
    add_line_item(pool["id"], "MANAGEMENT", 100000, "RECOVERABLE", is_variable=False)
    pool_after = validate_success(api.get_expense_pool(pool["id"], ACCT_HEADERS), 200)
    raw_sum = 500008 + 700008 + 100000
    assert pool_after["total_recoverable_cents"] == 1525020
    assert pool_after["total_recoverable_cents"] > raw_sum
