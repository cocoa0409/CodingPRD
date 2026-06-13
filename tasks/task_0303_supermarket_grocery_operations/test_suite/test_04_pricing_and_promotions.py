"""Weekly-ad pricing, promotions, and the effective-unit-price / line-extended-
price calculations.

Translates difficulty instances (queue A: dual_variant_calc,
resource_temporal_overlap) and corner instances (queue B: state_machines,
calculations, validations).
"""
from test_helpers import (
    validate_success, validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)

SM = TEST_USERS["store_manager_headers"]
PM = TEST_USERS["price_manager_headers"]
RC = TEST_USERS["receiving_clerk_headers"]
CSH = TEST_USERS["cashier_headers"]


def _setup_stacked_vs_everyday(api):
    """Two each-sold products at everyday 200c, on-hand 10:
      P1 has an ACTIVE ad price 150c and a STACKABLE 20%-off promo,
      P2 has NO ad and a NON-STACKABLE 20%-off promo.
    Returns (p1, p2, sale1_line, sale2_line) finalized.
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    dept = fixtures.create_department()
    p1 = fixtures.create_product(department_id=dept["id"], name="Chips A",
                                 sku="SKU-A", unit_price_cents=200, reorder_point_qty=0)
    p2 = fixtures.create_product(department_id=dept["id"], name="Chips B",
                                 sku="SKU-B", unit_price_cents=200, reorder_point_qty=0)
    fixtures.create_price_plan(p1["id"], 150, "2026-06-01T00:00:00Z",
                               "2026-06-30T00:00:00Z")
    fixtures.create_promotion(p1["id"], promo_type="PERCENT_OFF",
                              percent_off_bps=2000, stackable=True)
    fixtures.create_promotion(p2["id"], promo_type="PERCENT_OFF",
                              percent_off_bps=2000, stackable=False)
    fixtures.receive_lot(p1["id"], 10, unit_cost_cents=100)
    fixtures.receive_lot(p2["id"], 10, unit_cost_cents=100)
    sale1, line1 = fixtures.open_sale_with_each_line(p1["id"], 4)
    sale2, line2 = fixtures.open_sale_with_each_line(p2["id"], 4)
    fixtures.finalize_sale(sale1["id"])
    fixtures.finalize_sale(sale2["id"])
    line1 = get_success_data(api.get_sale_line_item(line1["id"], CSH))
    line2 = get_success_data(api.get_sale_line_item(line2["id"], CSH))
    return line1, line2


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / promo_discount_base_stacked_vs_everyday
# ---------------------------------------------------------------------------
def test_stackable_promo_discounts_off_applied_ad_price(api):
    """PRD §3.7: "When a promotion stacks on an applied ad price, the discount is
    computed off the already-reduced ad price because the gross used the ad
    price ..."
    PRD §3.7: "For a `PERCENT_OFF` promotion the discount is the gross multiplied by `percent_off_bps` divided by 10000, rounded half up, and the extended price is the gross minus that discount."

    Design: Difficulty/dual_variant_calc/promo_discount_base_stacked_vs_everyday
    """
    line1, _ = _setup_stacked_vs_everyday(api)
    # ad price 150 * 4 = 600 gross; 20% off -> 480.
    assert line1["unit_price_applied_cents"] == 150
    assert line1["extended_price_cents"] == 480


def test_nonstackable_promo_discounts_off_everyday_price(api):
    """PRD §3.7: "when no ad price covered the line, the discount is computed off
    the everyday price."
    PRD §3.7: "if there is none, it falls back to the product's everyday `unit_price_cents`."

    Design: Difficulty/dual_variant_calc/promo_discount_base_stacked_vs_everyday
    """
    _, line2 = _setup_stacked_vs_everyday(api)
    # everyday 200 * 4 = 800 gross; 20% off -> 640.
    assert line2["unit_price_applied_cents"] == 200
    assert line2["extended_price_cents"] == 640


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / priceplan_halfopen_window_selection_at_boundary
# ---------------------------------------------------------------------------
def test_priceplan_window_excludes_clock_at_exact_end(api):
    """PRD §2.8: "a window covers the clock when its inclusive start is at or
    before the clock and its exclusive end is strictly after the clock."
    PRD §3.7: "the candidate price plans for the line's product are those whose half-open window covers the clock — that is, whose `effective_start` is at or before the clock and whose `effective_end` is strictly after it ..."

    Design: Difficulty/resource_temporal_overlap/priceplan_halfopen_window_selection_at_boundary
    """
    fixtures.advance_clock("2026-06-01T00:00:00Z")
    product = fixtures.create_product(name="Juice", unit_price_cents=200, reorder_point_qty=0)
    fixtures.create_price_plan(product["id"], 150, "2026-06-01T00:00:00Z",
                               "2026-06-10T00:00:00Z")
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100)
    fixtures.advance_clock("2026-06-10T00:00:00Z")  # clock == effective_end -> excluded
    sale, line = fixtures.open_sale_with_each_line(product["id"], 1)
    fixtures.finalize_sale(sale["id"])
    line = get_success_data(api.get_sale_line_item(line["id"], CSH))
    assert line["unit_price_applied_cents"] == 200


def test_priceplan_window_excludes_clock_at_end_subtotal(api):
    """PRD §3.7: "if there is none, it falls back to the product's everyday `unit_price_cents`."
    PRD §3.7: "The `subtotal_cents` is the sum of the already-rounded `extended_price_cents` across all lines ..."

    Design: Difficulty/resource_temporal_overlap/priceplan_halfopen_window_selection_at_boundary
    """
    fixtures.advance_clock("2026-06-01T00:00:00Z")
    product = fixtures.create_product(name="Juice2", unit_price_cents=200, reorder_point_qty=0)
    fixtures.create_price_plan(product["id"], 150, "2026-06-01T00:00:00Z",
                               "2026-06-10T00:00:00Z")
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100)
    fixtures.advance_clock("2026-06-10T00:00:00Z")
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 1)
    finalized = fixtures.finalize_sale(sale["id"])
    assert finalized["subtotal_cents"] == 200


# ---------------------------------------------------------------------------
# Corner: calculations / fixed_off_promo_caps_at_gross
# ---------------------------------------------------------------------------
def test_fixed_off_promo_caps_at_gross(api):
    """PRD §3.7: "For a `FIXED_OFF` promotion (each-sold only) the discount is the smaller of the gross and the product of `fixed_off_cents` and `quantity`, and the extended price is the gross minus that discount."

    Design: Corner/calculations/fixed_off_promo_caps_at_gross
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Fixed", unit_price_cents=300, reorder_point_qty=0)
    fixtures.create_promotion(product["id"], promo_type="FIXED_OFF",
                              fixed_off_cents=50, stackable=False)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100)
    sale, line = fixtures.open_sale_with_each_line(product["id"], 3)
    finalized = fixtures.finalize_sale(sale["id"])
    line = get_success_data(api.get_sale_line_item(line["id"], CSH))
    # gross 900, discount min(900, 50*3)=150 -> 750.
    assert line["extended_price_cents"] == 750
    assert finalized["subtotal_cents"] == 750


# ---------------------------------------------------------------------------
# Corner: state_machines / cancel_priceplan_compensation_no_other_change
# ---------------------------------------------------------------------------
def test_cancel_scheduled_priceplan(api):
    """PRD §3.5: "A `PriceManager` may cancel a plan that is in `SCHEDULED` or `ACTIVE`, driving it to `CANCELLED`; a cancel attempt on a plan in any other state is rejected with `ERR_PRICE_PLAN_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_priceplan_compensation_no_other_change
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="PP", unit_price_cents=200, reorder_point_qty=0)
    plan = fixtures.create_price_plan(product["id"], 150, "2026-07-01T00:00:00Z",
                                      "2026-07-08T00:00:00Z")
    cancelled = validate_success(api.cancel_price_plan(plan["id"], PM))
    assert cancelled["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Corner: validations / priceplan_invalid_window_end_before_start
# ---------------------------------------------------------------------------
def test_priceplan_invalid_window_end_before_start(api):
    """PRD §2.8: "Price plans, promotions, and coupons all require their effective end to be strictly after their effective start; a window whose end is not strictly after its start is rejected with `ERR_INVALID_WINDOW` (HTTP 422)."

    Design: Corner/validations/priceplan_invalid_window_end_before_start
    """
    product = fixtures.create_product(name="Win", unit_price_cents=200, reorder_point_qty=0)
    resp = api.create_price_plan(
        {"product_id": product["id"], "ad_price_cents": 150,
         "effective_start": "2026-06-10T00:00:00Z",
         "effective_end": "2026-06-01T00:00:00Z",
         "expected_product_version": product["version"]}, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)
