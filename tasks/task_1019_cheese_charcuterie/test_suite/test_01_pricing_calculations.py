"""Pricing calculations: provisional/final line price, by-unit price, board per-component
rounding, wholesale volume discount, and catering delivery fee."""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_paid_retail_order, setup_allocated_wholesale_order,
    create_customer, create_by_unit_product, create_product, create_prep_station,
    create_order, add_unit_line, create_board, create_product_line_payload,
    create_tasting_event_payload, TEST_USERS,
)

CS = TEST_USERS["counter_staff_headers"]
SM = TEST_USERS["shop_manager_headers"]


# ─── dual_variant_calc / line_price_provisional_vs_final_on_orderline ───────
class TestLinePriceProvisionalVsFinal:
    def test_provisional_at_add_then_final_at_fulfill(self, api):
        """PRD §3.4: "For a by-weight product line the provisional price is the requested
        weight divided by 1000 (grams to kilograms) times the product's `price_per_kg_cents`,
        rounded half up to whole cents."
        PRD §3.5: "For each product line the system recomputes `final_price_cents` from the
        actual cut weight (by-weight lines reprice on the real cut; the final price may differ
        from the provisional), adds that actual weight to the lot's `consumed_weight_g`,
        subtracts it from the lot's `current_weight_g`, and releases the line's reservation."

        Design: Difficulty/dual_variant_calc/line_price_provisional_vs_final_on_orderline
        """
        sc = setup_paid_retail_order(price_per_kg_cents=4200, requested_weight_g=500,
                                     received_weight_g=2000)
        line = get_success_data(api.get_order_line(sc["line"]["id"], CS))
        assert line["provisional_price_cents"] == 2100, "500g @ 4200/kg -> 2100"

        api.fulfill_order(sc["order"]["id"],
                          {"line_actuals": [{"line_id": sc["line"]["id"], "actual_cut_weight_g": 520}]}, CS)
        fulfilled_line = get_success_data(api.get_order_line(sc["line"]["id"], CS))
        assert fulfilled_line["final_price_cents"] == 2184, "520g @ 4200/kg -> 2184"

    def test_fulfill_reaches_fulfilled_with_diverged_final_price(self, api):
        """PRD §3.5: "For each product line the system recomputes `final_price_cents` from the
        actual cut weight (by-weight lines reprice on the real cut; the final price may differ
        from the provisional), adds that actual weight to the lot's `consumed_weight_g`,
        subtracts it from the lot's `current_weight_g`, and releases the line's reservation."

        Design: Difficulty/dual_variant_calc/line_price_provisional_vs_final_on_orderline
        """
        sc = setup_paid_retail_order(price_per_kg_cents=4200, requested_weight_g=500,
                                     received_weight_g=2000)
        res = api.fulfill_order(
            sc["order"]["id"],
            {"line_actuals": [{"line_id": sc["line"]["id"], "actual_cut_weight_g": 520}]}, CS)
        order = validate_success(res, 200)
        assert order["fulfillment_status"] == "FULFILLED"
        line = get_success_data(api.get_order_line(sc["line"]["id"], CS))
        assert line["provisional_price_cents"] == 2100
        assert line["final_price_cents"] == 2184
        assert line["final_price_cents"] != line["provisional_price_cents"]


# ─── combinatorial_formula / wholesale_tiered_volume_discount_mode_a ────────
class TestWholesaleTieredDiscount:
    def test_tier1_discount_and_total_on_submit(self, api):
        """PRD §3.5: "a billable weight below 5000 grams (5 kilograms) earns no discount;
        from 5000 grams up to but not including 20000 grams (20 kilograms) earns 8 percent;
        20000 grams or more earns 15 percent."
        PRD §3.5: "`total_cents` is the subtotal minus the discount plus the delivery fee."

        Design: Difficulty/combinatorial_formula/wholesale_tiered_volume_discount_mode_a
        """
        sc = setup_allocated_wholesale_order(price_per_kg_cents=5000, requested_weight_g=6000,
                                             received_weight_g=10000)
        order = validate_success(api.submit_order(sc["order"]["id"], CS), 200)
        assert order["billable_weight_g"] == 6000
        assert order["subtotal_cents"] == 30000
        assert order["discount_cents"] == 2400, "round(30000 * 0.08) = 2400"
        assert order["total_cents"] == 27600

    def test_discount_persisted_on_reread(self, api):
        """PRD §3.5: "`discount_cents` is that percentage applied to the whole-cent subtotal,
        rounded half up, then capped at the maximum wholesale discount of 50000 cents (five
        hundred dollars) — whichever is smaller."

        Design: Difficulty/combinatorial_formula/wholesale_tiered_volume_discount_mode_a
        """
        sc = setup_allocated_wholesale_order(price_per_kg_cents=5000, requested_weight_g=6000,
                                             received_weight_g=10000)
        api.submit_order(sc["order"]["id"], CS)
        order = get_success_data(api.get_order(sc["order"]["id"], CS))
        assert order["discount_cents"] == 2400
        assert order["total_cents"] == 27600


# ─── combinatorial_formula / board_per_component_rounding_mode_b ────────────
class TestBoardPerComponentRounding:
    def _make_board(self, api):
        product = create_product(price_per_kg_cents=3350, milk_type="SHEEP", form="WEDGE")
        return create_board([
            {"product_id": product["id"], "portion_g": 75},
            {"product_id": product["id"], "portion_g": 75},
        ], name="Duo Board")

    def test_base_price_rounds_per_component_then_sums(self, api):
        """PRD §3.3: "The board's `base_price_cents` is computed by pricing each component
        independently — the component's `portion_g` divided by 1000 to convert grams to
        kilograms, multiplied by that product's `price_per_kg_cents`, and rounded half up to
        whole cents — then summing those rounded component prices, and finally adding a fixed
        assembly fee."

        Design: Difficulty/combinatorial_formula/board_per_component_rounding_mode_b
        """
        board = self._make_board(api)
        # round(75/1000 * 3350) = round(251.25) = 251 per component; 251+251 = 502; +1500 = 2002.
        assert board["base_price_cents"] == 2002

    def test_assembly_fee_fixed_at_1500(self, api):
        """PRD §3.3: "The board records that assembly fee in `assembly_fee_cents`, which is
        always the fixed `BOARD_ASSEMBLY_FEE_CENTS` of 1500 cents (fifteen dollars)."

        Design: Difficulty/combinatorial_formula/board_per_component_rounding_mode_b
        """
        board = self._make_board(api)
        assert board["assembly_fee_cents"] == 1500
        assert board["base_price_cents"] == 2002


# ─── Corner: calculations / corner_byunit_line_price ───────────────────────
def test_by_unit_line_price(api):
    """PRD §3.4: "For a by-unit product line it is the requested quantity times the product's
    `unit_price_cents`."

    Design: Corner/calculations/corner_byunit_line_price
    """
    customer = create_customer()
    product = create_by_unit_product(unit_price_cents=700)
    order = create_order(customer["id"], "RETAIL")
    res = api.add_order_line(order["id"], create_product_line_payload(product["id"], requested_qty=3), CS)
    line = validate_success(res, 201)
    assert line["provisional_price_cents"] == 2100, "qty 3 * 700 = 2100"


# ─── Corner: calculations / corner_wholesale_discount_tier_boundary_5000 ───
def test_wholesale_discount_tier_boundary_at_5000(api):
    """PRD §3.5: "a billable weight below 5000 grams (5 kilograms) earns no discount; from
    5000 grams up to but not including 20000 grams (20 kilograms) earns 8 percent; 20000 grams
    or more earns 15 percent."

    Design: Corner/calculations/corner_wholesale_discount_tier_boundary_5000
    """
    sc = setup_allocated_wholesale_order(price_per_kg_cents=5000, requested_weight_g=5000,
                                         received_weight_g=10000)
    order = validate_success(api.submit_order(sc["order"]["id"], CS), 200)
    assert order["billable_weight_g"] == 5000
    assert order["discount_cents"] == 2000, "exactly 5000g is inclusive: round(25000*0.08)=2000"
    assert order["total_cents"] == 23000


# ─── Corner: calculations / corner_catering_delivery_fee_applied ───────────
def test_catering_delivery_fee_applied(api):
    """PRD §3.5: "`delivery_fee_cents` is the fixed catering delivery fee of 2500 cents
    (twenty-five dollars) when the order type is `CATERING`, and zero otherwise."

    Design: Corner/calculations/corner_catering_delivery_fee_applied
    """
    customer = create_customer(name="Cater Host")
    station = create_prep_station(name="Station D")
    product = create_by_unit_product(name="Pate", form="SLICED", unit_price_cents=1000)
    order = create_order(customer["id"], "CATERING",
                         prep_station_id=station["id"],
                         prep_window_start="2026-08-05T09:00:00Z",
                         prep_window_end="2026-08-05T12:00:00Z",
                         event_date="2026-08-05T18:00:00Z")
    add_unit_line(order["id"], product["id"], 2)
    submitted = validate_success(api.submit_order(order["id"], CS), 200)
    assert submitted["delivery_fee_cents"] == 2500
    assert submitted["subtotal_cents"] == 2000, "qty 2 * 1000 = 2000"
    assert submitted["total_cents"] == 4500
