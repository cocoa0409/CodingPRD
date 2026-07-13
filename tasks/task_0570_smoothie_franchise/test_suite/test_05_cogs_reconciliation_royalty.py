"""Dual-variant COGS, royalty basis/rebate, store-posture precedence, reconciliation."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_open_store, create_ingredient, create_inventory_lot, create_menu_item,
    create_boost, create_customer, create_subscription, setup_order_env, suspend_store,
    place_order, pay_order, advance_order_to_completed, order_line, set_clock,
    make_customer_headers, make_store_staff_headers,
    create_order_payload, create_reconciliation_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/order_cogs_provisional_vs_final
# ---------------------------------------------------------------------------

def _cogs_order(api):
    fr, st = create_open_store(api)
    straw = create_ingredient(api, name="Strawberry", standard_cost_cents_per_unit=2)
    yog = create_ingredient(api, name="Yogurt", standard_cost_cents_per_unit=1)
    create_inventory_lot(api, st["id"], straw["id"], qty_received=200, unit_cost_cents=3)
    create_inventory_lot(api, st["id"], yog["id"], qty_received=200, unit_cost_cents=1)
    mi = create_menu_item(api, name="Classic Berry", category="SMOOTHIE", base_price_cents=500,
                          recipe=[{"ingredient_id": straw["id"], "base_qty": 100},
                                  {"ingredient_id": yog["id"], "base_qty": 80}],
                          base_calories=250)
    cust = create_customer(api, email="c1@x.com", full_name="C One")
    order = place_order(api, st["id"], cust["id"], [order_line(mi["id"], "MEDIUM")])
    return st, cust, order


def test_cogs_provisional_uses_standard_cost(api):
    """PRD §3.6: "The `cogs_provisional_cents` is the sum over ingredients of that
    ingredient's aggregate required units multiplied by its `standard_cost_cents_per_unit`
    (planning cost)."

    Design: Difficulty/dual_variant_calc/order_cogs_provisional_vs_final
    """
    st, cust, order = _cogs_order(api)
    paid = pay_order(api, order["id"], cust["id"])
    # straw ceil(100*1.5)=150 * std 2 = 300; yog ceil(80*1.5)=120 * std 1 = 120; total 420.
    assert paid["cogs_provisional_cents"] == 420, (
        f"Expected cogs_provisional 420, got {paid['cogs_provisional_cents']}"
    )


def test_cogs_final_uses_actual_lot_cost(api):
    """PRD §3.6: "Completion locks the final cost of goods: `cogs_final_cents` is the sum,
    over each unit consumed at payment, of that unit's source lot `unit_cost_cents` (the
    actual FIFO lot cost, which diverges from the provisional standard-cost figure
    whenever a lot's cost differs from standard)."

    Design: Difficulty/dual_variant_calc/order_cogs_provisional_vs_final
    """
    st, cust, order = _cogs_order(api)
    completed = advance_order_to_completed(api, order["id"], cust["id"], st["id"])
    # straw 150 * unit_cost 3 = 450; yog 120 * unit_cost 1 = 120; total 570.
    assert completed["cogs_final_cents"] == 570, (
        f"Expected cogs_final 570, got {completed['cogs_final_cents']}"
    )


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/royalty_gross_vs_net_basis
# ---------------------------------------------------------------------------

def _posted_gross_reconciliation(api):
    set_clock(api, "2026-06-01T12:00:00Z")
    fr, st = create_open_store(api)
    ing = create_ingredient(api, name="Spinach")
    create_inventory_lot(api, st["id"], ing["id"], qty_received=100, unit_cost_cents=2)
    mi = create_menu_item(api, name="Green Machine", category="SMOOTHIE", base_price_cents=500,
                          recipe=[{"ingredient_id": ing["id"], "base_qty": 50}], base_calories=200)
    boost = create_boost(api, name="Protein", price_cents=150, calories=100)
    cust = create_customer(api, email="c2@x.com", full_name="C Two")
    create_subscription(api, cust["id"], tier="BASIC", monthly_fee_cents=999,
                        included_smoothie_credits=4)
    order = place_order(api, st["id"], cust["id"], [order_line(mi["id"], "MEDIUM", [boost["id"]])],
                        use_subscription_credit=True)
    advance_order_to_completed(api, order["id"], cust["id"], st["id"])
    staff = make_store_staff_headers(st["id"])
    rec = validate_success(api.create_reconciliation(st["id"],
                                                     create_reconciliation_payload("2026-06-01"),
                                                     staff), expected_status=201)
    validate_success(api.count_reconciliation(rec["id"], {"counted_cash_cents": 162}, staff))
    posted = validate_success(
        api.post_reconciliation(rec["id"], {"royalty_basis": "GROSS"}, ADMIN)
    )
    return posted


def test_royalty_basis_sums_gross_and_net(api):
    """PRD §3.8: "Over that set, `expected_sales_cents` is the sum of `total_cents`,
    `gross_sales_cents` is the sum of `gross_merch_cents`, and `net_sales_cents` is the
    sum of `discounted_subtotal_cents`."

    Design: Difficulty/dual_variant_calc/royalty_gross_vs_net_basis
    """
    posted = _posted_gross_reconciliation(api)
    assert posted["gross_sales_cents"] == 750, (
        f"Expected gross_sales 750, got {posted['gross_sales_cents']}"
    )
    assert posted["net_sales_cents"] == 150, (
        f"Expected net_sales 150, got {posted['net_sales_cents']}"
    )


def test_royalty_due_on_gross_basis(api):
    """PRD §3.8: "The `basis_sales` is `net_sales_cents` when the basis is `NET` and
    `gross_sales_cents` when it is `GROSS`."
    PRD §3.8: "The `total_franchise_due_cents` is `royalty_due_cents` plus
    `marketing_fee_cents`."

    Design: Difficulty/dual_variant_calc/royalty_gross_vs_net_basis
    """
    posted = _posted_gross_reconciliation(api)
    # GROSS basis 750, no rebate (net 150 < 50000), rate 0.06: royalty round(45)=45;
    # marketing round(750*0.02)=15; total 60.
    assert posted["royalty_due_cents"] == 45, (
        f"Expected royalty_due 45, got {posted['royalty_due_cents']}"
    )
    assert posted["total_franchise_due_cents"] == 60, (
        f"Expected total_franchise_due 60, got {posted['total_franchise_due_cents']}"
    )


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/royalty_rebate_threshold_boundary
# ---------------------------------------------------------------------------

def _posted_net_reconciliation_at_threshold(api):
    set_clock(api, "2026-06-01T12:00:00Z")
    fr, st = create_open_store(api)
    ing = create_ingredient(api, name="Acai")
    create_inventory_lot(api, st["id"], ing["id"], qty_received=100, unit_cost_cents=2)
    mi = create_menu_item(api, name="Mega Pack", category="WELLNESS_PACK", base_price_cents=50000,
                          recipe=[{"ingredient_id": ing["id"], "base_qty": 1}], base_calories=900)
    cust = create_customer(api, email="c11@x.com", full_name="C Eleven")
    order = place_order(api, st["id"], cust["id"], [order_line(mi["id"], "SMALL")])
    advance_order_to_completed(api, order["id"], cust["id"], st["id"])
    staff = make_store_staff_headers(st["id"])
    rec = validate_success(api.create_reconciliation(st["id"],
                                                     create_reconciliation_payload("2026-06-01"),
                                                     staff), expected_status=201)
    validate_success(api.count_reconciliation(rec["id"], {"counted_cash_cents": 54000}, staff))
    posted = validate_success(
        api.post_reconciliation(rec["id"], {"royalty_basis": "NET"}, ADMIN)
    )
    return posted


def test_rebate_applies_at_threshold_net_sales(api):
    """PRD §3.8: "if `net_sales_cents` is at least 50000 cents, the `royalty_rate_applied`
    drops to a flat 5% (0.05); otherwise it is the effective rate just described. The
    rebate boundary is inclusive — net sales of exactly 50000 trigger the rebate, and
    49999 do not."

    Design: Difficulty/boundary_precision_check/royalty_rebate_threshold_boundary
    """
    posted = _posted_net_reconciliation_at_threshold(api)
    assert posted["net_sales_cents"] == 50000, (
        f"Expected net_sales 50000, got {posted['net_sales_cents']}"
    )
    assert posted["royalty_rate_applied"] == pytest.approx(0.05), (
        f"Expected rebate rate 0.05, got {posted['royalty_rate_applied']}"
    )
    assert posted["royalty_due_cents"] == 2500, (
        f"Expected royalty_due 2500, got {posted['royalty_due_cents']}"
    )


def test_rebate_total_franchise_due(api):
    """PRD §3.8: "The `royalty_due_cents` is `basis_sales` multiplied by
    `royalty_rate_applied`, rounded half up."
    PRD §3.8: "The `total_franchise_due_cents` is `royalty_due_cents` plus
    `marketing_fee_cents`."

    Design: Difficulty/boundary_precision_check/royalty_rebate_threshold_boundary
    """
    posted = _posted_net_reconciliation_at_threshold(api)
    # royalty 2500 + marketing round(50000*0.02)=1000 = 3500.
    assert posted["total_franchise_due_cents"] == 3500, (
        f"Expected total_franchise_due 3500, got {posted['total_franchise_due_cents']}"
    )


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/store_state_beats_points_fiscal
# The PRD's fixed evaluation order (§2.9) places store operating posture (gate 7)
# ahead of the beyond-gate business rules such as the points-balance check, so a
# suspended store yields ERR_STORE_NOT_OPEN regardless of the redemption problem.
# ---------------------------------------------------------------------------

def test_suspended_store_beats_over_redemption(api):
    """PRD §2.9: "When more than one validation could reject a request, the checks are
    evaluated in a fixed priority order so that the earliest failing check determines the
    returned error."
    PRD §2.9: "Store operating posture — where required, the store is `OPEN`, else
    `ERR_STORE_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/store_state_beats_points_fiscal
    """
    env = setup_order_env(api)
    suspend_store(api, env["store"])
    resp = api.create_order(
        create_order_payload(env["store"]["id"], [order_line(env["menu_item"]["id"], "SMALL")],
                             redeem_points=10),
        make_customer_headers(env["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STORE_NOT_OPEN.value)


def test_placing_at_suspended_store_rejected(api):
    """PRD §3.5: "The store must be `OPEN` to accept an order, otherwise placement is
    rejected with `ERR_STORE_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/store_state_beats_points_fiscal
    """
    env = setup_order_env(api)
    suspend_store(api, env["store"])
    resp = api.create_order(
        create_order_payload(env["store"]["id"], [order_line(env["menu_item"]["id"], "SMALL")]),
        make_customer_headers(env["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STORE_NOT_OPEN.value)


# ---------------------------------------------------------------------------
# Corner/validations/duplicate_reconciliation_returns_exists
# ---------------------------------------------------------------------------

def test_duplicate_reconciliation_returns_exists(api):
    """PRD §3.8: "At most one non-posted reconciliation may exist for a given store and
    business date; a second is rejected with `ERR_RECONCILIATION_EXISTS`."

    Design: Corner/validations/duplicate_reconciliation_returns_exists
    """
    fr, st = create_open_store(api)
    staff = make_store_staff_headers(st["id"])
    validate_success(api.create_reconciliation(st["id"],
                                               create_reconciliation_payload("2026-06-01"),
                                               staff), expected_status=201)
    resp = api.create_reconciliation(st["id"], create_reconciliation_payload("2026-06-01"), staff)
    validate_error(resp, ApiErrorId.ERR_RECONCILIATION_EXISTS.value)
