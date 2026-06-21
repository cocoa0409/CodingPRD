"""Calculation corner cases: percentage rent above breakpoint, CPI floor, gross-up
filtering, admin fee, line-item delete recompute, occupied-basis pro-rata
(breadth queue B — calculations section).
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_lease_with_sales,
    create_property, create_tenant, create_active_lease, create_pool, add_line_item,
    create_reconciliation,
    PM_HEADERS, ACCT_HEADERS,
)


def test_percentage_rent_above_breakpoint_charge(api):
    """PRD §3.5: "The excess is the report's gross_sales_cents minus the lease's
    pct_rent_breakpoint_cents, and if that difference is negative the excess is
    zero. The percentage-rent charge is that excess multiplied by the lease's
    pct_rent_rate, rounded half-up to whole cents."

    Design: Corner/calculations/percentage_rent_above_breakpoint_charge
    """
    # excess 5000000-3000000=2000000 *0.06 = 120000.
    prop, tenant, lease, sr = setup_lease_with_sales(
        pct_rent_rate=0.06, pct_rent_breakpoint_cents=3000000,
        gross_sales_cents=5000000, period_year=2025)
    validate_success(api.run_percentage_rent(lease["id"], {"period_year": 2025}, PM_HEADERS), 200)
    after = validate_success(api.get_lease(lease["id"], PM_HEADERS), 200)
    assert after["outstanding_balance_cents"] == 120000


def test_cpi_floor_no_decrease_on_index_drop(api):
    """PRD §3.4: "first a floor, so a raw increase below zero is treated as zero
    (CPI escalation never decreases rent)"

    Design: Corner/calculations/cpi_floor_no_decrease_on_index_drop
    """
    prop = create_property(total_rentable_sqft=100000)
    tenant = create_tenant()
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=10000000,
                                escalation_type="CPI", escalation_rate=0.04,
                                cpi_base_index=250.0)
    escalated = validate_success(
        api.escalate_lease(lease["id"], {"current_cpi_index": 240.0}, PM_HEADERS), 200)
    assert escalated["base_rent_cents_annual"] == 10000000


def test_gross_up_excludes_non_recoverable(api):
    """PRD §3.2: "The system then walks every line item whose recoverability is
    either RECOVERABLE or CAPPED_CONTROLLABLE (items marked NON_RECOVERABLE are
    skipped)."

    Design: Corner/calculations/gross_up_excludes_non_recoverable
    """
    prop = create_property(total_rentable_sqft=10000)
    pool = create_pool(prop["id"], pool_year=2025, admin_fee_pct=0)
    add_line_item(pool["id"], "INSURANCE", 200000, "RECOVERABLE", is_variable=False)
    add_line_item(pool["id"], "MANAGEMENT", 999999, "NON_RECOVERABLE", is_variable=False)
    pool_after = validate_success(api.get_expense_pool(pool["id"], ACCT_HEADERS), 200)
    assert pool_after["total_recoverable_cents"] == 200000


def test_admin_fee_applied_after_sum(api):
    """PRD §3.2: "Finally the administrative fee is applied to that subtotal:
    total_recoverable_cents is the recoverable subtotal plus the subtotal
    multiplied by the pool's admin_fee_pct, rounded half-up to whole cents."

    Design: Corner/calculations/admin_fee_applied_after_sum
    """
    # 200000 fixed (no gross-up) + round_half_up(200000*0.15)=30000 = 230000.
    prop = create_property(total_rentable_sqft=10000)
    pool = create_pool(prop["id"], pool_year=2025, admin_fee_pct=0.15)
    add_line_item(pool["id"], "INSURANCE", 200000, "RECOVERABLE", is_variable=False)
    pool_after = validate_success(api.get_expense_pool(pool["id"], ACCT_HEADERS), 200)
    assert pool_after["total_recoverable_cents"] == 230000


def test_line_item_delete_recomputes_pool_total(api):
    """PRD §3.2: "Removing a line item, addressed by its item_id under the owning
    pool, is permitted only while the pool is still OPEN; the removal returns the
    pool with its recomputed total."

    Design: Corner/calculations/line_item_delete_recomputes_pool_total
    """
    prop = create_property(total_rentable_sqft=10000)
    pool = create_pool(prop["id"], pool_year=2025, admin_fee_pct=0)
    item1 = add_line_item(pool["id"], "INSURANCE", 200000, "RECOVERABLE", is_variable=False)
    add_line_item(pool["id"], "TAXES", 300000, "RECOVERABLE", is_variable=False)
    pool_after = validate_success(
        api.delete_line_item(pool["id"], item1["id"], ACCT_HEADERS), 200)
    assert pool_after["total_recoverable_cents"] == 300000


def test_pro_rata_occupied_basis_variant(api):
    """PRD §3.7: "the denominator belongs to the pool's property ... and is the
    property's total_rentable_sqft when the pool's pro_rata_denominator is
    TOTAL_RENTABLE or its live occupied_sqft when OCCUPIED. Choosing OCCUPIED yields
    a smaller denominator and therefore a larger share"

    Design: Corner/calculations/pro_rata_occupied_basis_variant
    """
    # total 10000, occupied 5000 (two 2500 leases); OCCUPIED basis -> share 0.5;
    # recoverable fixed 1000000 -> reconciled 500000; estimated 0 -> true_up 500000.
    prop = create_property(total_rentable_sqft=10000)
    t1 = create_tenant("T1", "t1@x.com")
    t2 = create_tenant("T2", "t2@x.com")
    lease1 = create_active_lease(prop["id"], t1["id"], leased_sqft=2500,
                                 base_rent_cents_annual=0, estimated_cam_cents_monthly=0)
    create_active_lease(prop["id"], t2["id"], leased_sqft=2500,
                        base_rent_cents_annual=0, estimated_cam_cents_monthly=0)
    pool = create_pool(prop["id"], pool_year=2025,
                       pro_rata_denominator="OCCUPIED", admin_fee_pct=0)
    add_line_item(pool["id"], "INSURANCE", 1000000, "RECOVERABLE", is_variable=False)
    recon = create_reconciliation(lease1["id"], pool["id"], 2025)
    preview = validate_success(api.preview_reconciliation(recon["id"], ACCT_HEADERS), 200)
    assert preview["reconciled_cam_cents"] == 500000
    assert preview["true_up_cents"] == 500000
