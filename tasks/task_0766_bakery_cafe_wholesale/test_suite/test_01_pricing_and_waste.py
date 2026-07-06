"""Wholesale contract pricing, statement invoicing, and end-of-day waste reconciliation."""
from test_helpers import (
    validate_success, get_success_data,
    setup_committed_line, setup_committed_line_with_account,
    make_product, make_oven, make_account, make_bake_plan, add_line, commit_plan,
    make_bake_lot, make_retail_sale, make_delivery_order, deliver_order,
    set_clock, get_plan, get_line, TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]


def _reconciliation_scenario(api):
    """Baked 50 against par 40, 30 sold retail, 8 delivered wholesale, then reconcile.

    theoretical_waste = max(0, 50-40) = 10 ; actual_waste = max(0, 50-30-8) = 12 ;
    waste_value = 12 * 400 = 4800.
    """
    product = make_product(api, base_price_cents=400, shelf_life_hours=12)
    oven = make_oven(api)
    account = make_account(api, credit_limit_cents=1_000_000, contract_tier="STANDARD")
    plan = make_bake_plan(api, production_date="2026-06-02T00:00:00Z")
    line = add_line(api, plan["id"], product["id"], 40)
    commit_plan(api, plan["id"])
    set_clock(api, "2026-06-02T06:00:00Z")
    lot = make_bake_lot(api, line["id"], oven["id"], baked_qty=50,
                        produced_at="2026-06-02T05:00:00Z",
                        slot_start="2026-06-02T04:00:00Z", slot_end="2026-06-02T05:00:00Z")
    make_retail_sale(api, lot["id"], 30)
    deliver_order(api, account["id"], product["id"], line["id"], qty=8,
                  delivery_date="2026-06-02T10:00:00Z")
    validate_success(api.reconcile_bake_plan(plan["id"], MANAGER))
    return plan["id"], line["id"]


class TestReconciliationDualWaste:
    def test_reconcile_sets_plan_theoretical_and_actual_waste_totals(self, api):
        """PRD 3.5: "The theoretical waste ... is the amount by which the baked total
        exceeds the line's par_qty, floored at zero" and "The actual waste ... is the
        baked total minus the sold figure minus the delivered figure, floored at zero".
        PRD 3.5: "total_theoretical_waste_units is the sum of every line's
        theoretical_waste_units; total_actual_waste_units is the sum of every line's
        actual_waste_units; and total_waste_value_cents is the sum, over lines, of each
        line's actual_waste_units multiplied by its product's base_price_cents."

        Design: Difficulty/dual_variant_calc/reconciliation_par_vs_sales_waste
        """
        plan_id, _ = _reconciliation_scenario(api)
        plan = get_plan(api, plan_id)
        assert plan["total_theoretical_waste_units"] == 10, plan
        assert plan["total_actual_waste_units"] == 12, plan
        assert plan["total_waste_value_cents"] == 4800, plan
        assert plan["status"] == "RECONCILED", plan

    def test_reconcile_sets_per_line_theoretical_and_actual_waste(self, api):
        """PRD 3.5: "The theoretical waste ... is written to the line's
        theoretical_waste_units" and "The actual waste ... is written to the line's
        actual_waste_units."

        Design: Difficulty/dual_variant_calc/reconciliation_par_vs_sales_waste
        """
        _, line_id = _reconciliation_scenario(api)
        line = get_line(api, line_id)
        assert line["theoretical_waste_units"] == 10, line
        assert line["actual_waste_units"] == 12, line


class TestContractVsListPrice:
    def _order(self, api):
        ctx = setup_committed_line_with_account(
            api, base_price_cents=333, par_qty=20, contract_tier="STANDARD",
            production_date="2026-06-03T00:00:00Z")
        return get_success_data(api.create_delivery_order({
            "wholesale_account_id": ctx["account"]["id"], "product_id": ctx["product"]["id"],
            "bake_plan_line_id": ctx["line"]["id"], "delivery_date": "2026-06-03T10:00:00Z",
            "qty": 1}, MANAGER))

    def test_contract_variant_prices_line_total_with_tier_discount(self, api):
        """PRD 3.6: "The booked line_total_cents is the ordered quantity times the base
        price times one minus the effective discount, with the multiplication performed
        on the exact discounted amount and the rounding applied once at the end."

        Design: Difficulty/dual_variant_calc/wholesale_list_vs_contract_price
        """
        order = self._order(api)
        assert order["line_total_cents"] == 300, order
        assert order["unit_price_cents"] == 300, order

    def test_list_variant_is_undiscounted_and_diverges_from_contract(self, api):
        """PRD 3.6: "The reference list_total_cents is simply the quantity times the base
        price with no discount, and diverges from the booked total by exactly the discount
        whenever a discount applies."

        Design: Difficulty/dual_variant_calc/wholesale_list_vs_contract_price
        """
        order = self._order(api)
        assert order["list_total_cents"] == 333, order


class TestStatementRoundPerLineThenSum:
    def _statement(self, api):
        prod_a = make_product(api, base_price_cents=333, shelf_life_hours=12)
        prod_b = make_product(api, base_price_cents=555, shelf_life_hours=12)
        account = make_account(api, credit_limit_cents=1_000_000, contract_tier="STANDARD")
        plan = make_bake_plan(api, production_date="2026-06-05T00:00:00Z")
        line_a = add_line(api, plan["id"], prod_a["id"], 10)
        line_b = add_line(api, plan["id"], prod_b["id"], 10)
        commit_plan(api, plan["id"])
        deliver_order(api, account["id"], prod_a["id"], line_a["id"], qty=1,
                      delivery_date="2026-06-05T10:00:00Z")
        deliver_order(api, account["id"], prod_b["id"], line_b["id"], qty=1,
                      delivery_date="2026-06-05T10:00:00Z")
        return validate_success(
            api.get_statement(account["id"], "2026-06-05T10:00:00Z", MANAGER))

    def test_statement_sums_pre_rounded_line_totals(self, api):
        """PRD 3.9: "invoice_total_cents, the sum of those orders' already-rounded
        line_total_cents". PRD 2.6: "a statement sums the already-rounded per-line totals
        of the qualifying orders; it does not re-derive the invoice by summing exact
        discounted amounts and rounding a single time at the very end."

        Design: Difficulty/combinatorial_formula/invoice_round_per_line_then_sum_mode_b
        """
        stmt = self._statement(api)
        # round(299.7)=300 + round(499.5)=500 => 800 (sum-exact-then-round would give 799)
        assert stmt["invoice_total_cents"] == 800, stmt
        assert stmt["order_count"] == 2, stmt

    def test_statement_list_total_sums_undiscounted_line_references(self, api):
        """PRD 3.9: "list_total_cents, the sum of their list_total_cents".

        Design: Difficulty/combinatorial_formula/invoice_round_per_line_then_sum_mode_b
        """
        stmt = self._statement(api)
        assert stmt["list_total_cents"] == 888, stmt  # 333 + 555


class TestBulkVolumeFloor:
    def test_qty_at_bulk_min_applies_bulk_volume_floor_discount(self, api):
        """PRD 3.6: "A volume floor then applies: when the ordered quantity is at least 24
        units, the discount is raised to no less than the bulk rate of 20% (that is, the
        greater of the tier discount and 20%)."

        Design: Corner/calculations/bulk_volume_floor_discount_on_qty_24
        """
        ctx = setup_committed_line_with_account(
            api, base_price_cents=400, par_qty=30, contract_tier="STANDARD",
            production_date="2026-06-24T00:00:00Z")
        order = get_success_data(api.create_delivery_order({
            "wholesale_account_id": ctx["account"]["id"], "product_id": ctx["product"]["id"],
            "bake_plan_line_id": ctx["line"]["id"], "delivery_date": "2026-06-24T10:00:00Z",
            "qty": 24}, MANAGER))
        assert order["unit_price_cents"] == 320, order       # round(400*0.8)
        assert order["line_total_cents"] == 7680, order      # round(24*400*0.8)
        assert order["list_total_cents"] == 9600, order      # 24*400


class TestStatementEmpty:
    def test_statement_with_no_delivered_orders_is_zero(self, api):
        """PRD 3.9: "The statement gathers the account's delivery orders for that exact
        delivery_date whose fulfillment_status is DELIVERED and returns three figures:
        invoice_total_cents ... and order_count, the number of qualifying orders."

        Design: Corner/endpoints/statement_for_date_with_no_delivered_orders_is_zero
        """
        account = make_account(api, credit_limit_cents=1_000_000, contract_tier="STANDARD")
        stmt = validate_success(
            api.get_statement(account["id"], "2026-07-03T10:00:00Z", MANAGER))
        assert stmt["invoice_total_cents"] == 0, stmt
        assert stmt["order_count"] == 0, stmt
