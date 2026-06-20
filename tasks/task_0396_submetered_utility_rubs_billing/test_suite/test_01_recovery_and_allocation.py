"""Vendor-bill recovery (common-area deduction + state-law cap) and the two
allocation modes (consumption vs RUBS), including largest-remainder rounding.

Covers queue-A difficulty rules dual_variant_calc and combinatorial_formula
(allocation mode), and queue-B corner calculations / consistency_model instances.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    create_property_payload, create_utility_payload, create_vendor_bill_payload,
    setup_two_unit_consumption_cycle, setup_two_unit_rubs_cycle,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["property_manager_headers"]


def _approved_vendor_bill(api, total_cost_cents, recovery_cap_pct, common_area_pct):
    prop = get_success_data(
        api.create_property(
            create_property_payload(
                state_code="CA",
                recovery_cap_pct=recovery_cap_pct,
                common_area_pct=common_area_pct,
            ),
            PM,
        )
    )
    util = get_success_data(
        api.create_utility(create_utility_payload(prop["id"], allocation_method="CONSUMPTION"), PM)
    )
    vb = get_success_data(
        api.create_vendor_bill(
            create_vendor_bill_payload(prop["id"], util["id"], total_cost_cents=total_cost_cents),
            PM,
        )
    )
    return validate_success(api.approve_vendor_bill(vb["id"], PM))


# --------------------------------------------------------------------------- #
# dual_variant_calc / vendor_recoverable_cap_binds_vs_deduction_binds
# --------------------------------------------------------------------------- #
def test_vendor_recoverable_cap_binds(api):
    """PRD §3.4: "When the post-deduction amount exceeds the cap, the state-law
    ceiling binds and `recoverable_cents` equals `cap_cents`; when the
    post-deduction amount is less than or equal to the cap, the common-area
    deduction binds and `recoverable_cents` equals the total minus the
    common-area reserve."
    PRD §3.4: "the common-area reserve is computed as the floor of the bill's
    `total_cost_cents` multiplied by the property's `common_area_pct`"

    Design: Difficulty/dual_variant_calc/vendor_recoverable_cap_binds_vs_deduction_binds
    """
    data = _approved_vendor_bill(api, 100000, recovery_cap_pct=0.85, common_area_pct=0.10)
    assert data["common_area_cents"] == 10000
    assert data["cap_cents"] == 85000
    # post-deduction 90000 > cap 85000 -> cap binds
    assert data["recoverable_cents"] == 85000


def test_vendor_recoverable_deduction_binds(api):
    """PRD §3.4: "When the post-deduction amount exceeds the cap, the state-law
    ceiling binds and `recoverable_cents` equals `cap_cents`; when the
    post-deduction amount is less than or equal to the cap, the common-area
    deduction binds and `recoverable_cents` equals the total minus the
    common-area reserve."
    PRD §3.4: "the state-law ceiling is computed as the floor of
    `total_cost_cents` multiplied by the property's `recovery_cap_pct`, and
    stored in `cap_cents`."

    Design: Difficulty/dual_variant_calc/vendor_recoverable_cap_binds_vs_deduction_binds
    """
    data = _approved_vendor_bill(api, 100000, recovery_cap_pct=0.95, common_area_pct=0.10)
    assert data["common_area_cents"] == 10000
    assert data["cap_cents"] == 95000
    # post-deduction 90000 <= cap 95000 -> deduction binds
    assert data["recoverable_cents"] == 90000


# --------------------------------------------------------------------------- #
# dual_variant_calc / consumption_vs_rubs_allocation_diverge_same_pool
# --------------------------------------------------------------------------- #
def test_consumption_allocation_splits_by_metered_consumption(api):
    """PRD §3.7: "Each unit's floor share is the floor of the recoverable pool
    multiplied by that unit's consumption divided by the total consumption."

    Design: Difficulty/dual_variant_calc/consumption_vs_rubs_allocation_diverge_same_pool
    """
    bundle = setup_two_unit_consumption_cycle(consumption_a=2, consumption_b=1)
    assert bundle["statement_a"]["utility_charge_cents"] == 6667
    assert bundle["statement_b"]["utility_charge_cents"] == 3333
    total = (
        bundle["statement_a"]["utility_charge_cents"]
        + bundle["statement_b"]["utility_charge_cents"]
    )
    assert total == 10000


def test_rubs_allocation_splits_by_occupant_count(api):
    """PRD §3.7: "The total weight is the sum over the billed units of each
    unit's active lease `occupant_count`. Each unit's floor share is the floor
    of the recoverable pool multiplied by that unit's occupant count divided by
    the total weight"

    Design: Difficulty/dual_variant_calc/consumption_vs_rubs_allocation_diverge_same_pool
    """
    bundle = setup_two_unit_rubs_cycle(occupant_a=3, occupant_b=2)
    assert bundle["statement_a"]["utility_charge_cents"] == 6000
    assert bundle["statement_b"]["utility_charge_cents"] == 4000
    total = (
        bundle["statement_a"]["utility_charge_cents"]
        + bundle["statement_b"]["utility_charge_cents"]
    )
    assert total == 10000


# --------------------------------------------------------------------------- #
# combinatorial_formula / allocation_rounding_order_floor_then_largest_remainder
# --------------------------------------------------------------------------- #
def test_allocation_floor_then_largest_remainder_distribution(api):
    """PRD §3.7: "Because flooring each share leaves a remainder, the leftover
    cents — the recoverable pool minus the sum of all the floor shares — are
    distributed one cent at a time to units, taken in order of descending
    consumption and, where two units have equal consumption, ascending unit
    creation timestamp."

    Design: Difficulty/combinatorial_formula/allocation_rounding_order_floor_then_largest_remainder
    """
    bundle = setup_two_unit_consumption_cycle(consumption_a=2, consumption_b=1)
    # floor shares 6666 / 3333 (sum 9999); the single remainder cent goes to the
    # higher-consumption unit -> 6667 / 3333.
    assert bundle["statement_a"]["utility_charge_cents"] == 6667  # 6666 floor + 1 remainder
    assert bundle["statement_b"]["utility_charge_cents"] == 3333  # 3333 floor + 0 remainder


def test_allocation_conserves_recoverable_pool_exactly(api):
    """PRD §3.7: "Each unit's final utility charge is its floor share plus any
    remainder cents it received."

    Design: Difficulty/combinatorial_formula/allocation_rounding_order_floor_then_largest_remainder
    """
    bundle = setup_two_unit_consumption_cycle(consumption_a=2, consumption_b=1)
    total = (
        bundle["statement_a"]["utility_charge_cents"]
        + bundle["statement_b"]["utility_charge_cents"]
    )
    # no cent lost or created by the rounding order; equals recoverable_cents
    assert total == 10000


# --------------------------------------------------------------------------- #
# Corner: consistency_model / vendor_bill_approve_returns_computed_fields_same_response
# --------------------------------------------------------------------------- #
def test_approve_returns_computed_recovery_fields_in_same_response(api):
    """PRD §3.4: "Approving a vendor bill moves it from `RECEIVED` to `APPROVED`
    and is where the two ceilings are computed."
    PRD §3.4: "When the post-deduction amount exceeds the cap, the state-law
    ceiling binds and `recoverable_cents` equals `cap_cents`"

    Design: Corner/consistency_model/vendor_bill_approve_returns_computed_fields_same_response
    """
    data = _approved_vendor_bill(api, 100000, recovery_cap_pct=0.85, common_area_pct=0.10)
    assert data["common_area_cents"] == 10000
    assert data["cap_cents"] == 85000
    assert data["recoverable_cents"] == 85000
    assert data["status"] == "APPROVED"


# --------------------------------------------------------------------------- #
# Corner: calculations / zero_total_consumption_allocates_nothing_to_tenants
# --------------------------------------------------------------------------- #
def test_zero_total_consumption_allocates_nothing(api):
    """PRD §3.7: "When the total consumption for the period is zero, every
    unit's utility charge is zero and the recoverable pool is left unallocated
    (it is absorbed as a common-area shortfall rather than charged to tenants)."

    Design: Corner/calculations/zero_total_consumption_allocates_nothing_to_tenants
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA", common_area_pct=0.00)
    util = fx.create_utility(prop["id"], allocation_method="CONSUMPTION", monthly_admin_fee_cents=0)
    unit = fx.create_unit(prop["id"], unit_number="Z1")
    fx.create_active_lease(unit["id"], prop["id"], "tZ")
    meter = fx.create_and_assign_meter(prop["id"], util["id"], unit["id"], "ZS1")
    vb = fx.create_approved_vendor_bill(prop["id"], util["id"], total_cost_cents=30000)
    cycle = fx.open_billing_cycle(prop["id"], util["id"], vb["id"])
    fx.submit_and_validate_read(meter["id"], prop["id"], reading_value=0)
    get_success_data(api.lock_reads(cycle["id"], PM))
    get_success_data(api.allocate_cycle(cycle["id"], PM))
    get_success_data(api.issue_statements(cycle["id"], PM))
    statements = get_success_data(api.list_statements(PM, params={"billing_cycle_id": cycle["id"]}))
    assert statements[0]["utility_charge_cents"] == 0
    cycle_after = get_success_data(api.get_billing_cycle(cycle["id"], PM))
    assert cycle_after["allocated_total_cents"] == 0


# --------------------------------------------------------------------------- #
# Corner: calculations / admin_fee_proration_partial_occupancy_floor
# --------------------------------------------------------------------------- #
def test_admin_fee_prorated_partial_occupancy(api):
    """PRD §3.7: "Otherwise the `admin_fee_cents` is the floor of the utility's
    `monthly_admin_fee_cents` multiplied by the occupied days divided by the
    period days."

    Design: Corner/calculations/admin_fee_proration_partial_occupancy_floor
    """
    fx.set_clock("2026-06-29T00:00:00Z")
    prop = fx.create_property(state_code="CA", common_area_pct=0.00)
    util = fx.create_utility(prop["id"], allocation_method="RUBS", monthly_admin_fee_cents=3000)
    unit = fx.create_unit(prop["id"], unit_number="AF1")
    fx.create_active_lease(unit["id"], prop["id"], "tAF", move_in_date="2026-06-16T00:00:00Z")
    vb = fx.create_approved_vendor_bill(prop["id"], util["id"], total_cost_cents=30000)
    cycle = fx.open_billing_cycle(prop["id"], util["id"], vb["id"])
    get_success_data(api.lock_reads(cycle["id"], PM))
    get_success_data(api.allocate_cycle(cycle["id"], PM))
    get_success_data(api.issue_statements(cycle["id"], PM))
    statements = get_success_data(api.list_statements(PM, params={"billing_cycle_id": cycle["id"]}))
    # 15 inclusive occupied days of a 30-day period: floor(3000*15/30) = 1500
    assert statements[0]["admin_fee_cents"] == 1500
