"""Sale finalize pricing: FEFO cost-of-goods vs book-value rollup divergence,
per-line-then-sum rounding, the coupon gate keyed on subtotal, FEFO ordering, and
insufficient-stock filtering.

Translates difficulty instances (queue A: dual_variant_calc,
combinatorial_formula) and corner instances (queue B: calculations, validations,
consistency_model).
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
AUD = TEST_USERS["inventory_auditor_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / fefo_cogs_vs_book_value_rollup_diverge
# Weighed product 100 c/lb; Lot1 1000 milli @ 80 c/lb (exp soonest),
# Lot2 5000 milli @ 100 c/lb; sell 1500 milli weighed.
#   cogs (FEFO): 1000@80 -> rhu(1000*80/1000)=80; 500@100 -> rhu(500*100/1000)=50 => 130
#   on_hand after: 4500 milli; value = rhu(4500*100/1000)=450 (only lot2 survives)
# ---------------------------------------------------------------------------
def _setup_diverge(api):
    fixtures.advance_clock("2026-06-01T00:00:00Z")
    dept = fixtures.create_department(name="Produce")
    product = fixtures.create_weighed_product(
        department_id=dept["id"], name="Bananas", plu="4011",
        unit_price_cents=100, is_perishable=True, reorder_point_qty=0)
    # Lot1: 1000 milli @ 80, expires soonest 2026-06-10.
    fixtures.receive_lot(product["id"], 1000, unit_cost_cents=80,
                         expiration_date="2026-06-10T00:00:00Z",
                         expected_total_cents=580)
    # Lot2: 5000 milli @ 100, expires later 2026-06-20.
    fixtures.receive_lot(product["id"], 5000, unit_cost_cents=100,
                         expiration_date="2026-06-20T00:00:00Z",
                         expected_total_cents=500, override_variance=False)
    sale = fixtures.open_sale()
    fixtures.add_weighed_line(sale["id"], product["id"], 1500)
    return product, sale


def test_fefo_cogs_accumulates_over_depleted_lots(api):
    """PRD §3.8: "For a weighed product the cost taken from a lot is the units taken multiplied by the lot's `unit_cost_cents` divided by 1000, rounded half up per lot before being added ... The accumulated figure becomes the sale's `cogs_cents`."
    PRD §3.8: "Eligible lots are consumed in order of soonest expiration first (lots with no expiration date sort last), then by earliest `created_at`."

    Design: Difficulty/dual_variant_calc/fefo_cogs_vs_book_value_rollup_diverge
    """
    product, sale = _setup_diverge(api)
    finalized = fixtures.finalize_sale(sale["id"])
    assert finalized["cogs_cents"] == 130


def test_book_value_rollup_over_surviving_lots_diverges_from_cogs(api):
    """PRD §3.8: "Note that this book-value rollup and the FEFO cost-of-goods accumulation are deliberately distinct: the rollup values every on-hand lot (`ACTIVE` and `QUARANTINED` alike) while cost of goods values only the lots actually depleted, drawn only from `ACTIVE`, non-expired lots."
    PRD §3.4: "for a weighed product, the lot's remaining milli-units multiplied by its `unit_cost_cents` and divided by 1000 with the result rounded half up before being added ..."

    Design: Difficulty/dual_variant_calc/fefo_cogs_vs_book_value_rollup_diverge
    """
    product, sale = _setup_diverge(api)
    finalized = fixtures.finalize_sale(sale["id"])
    prod = get_success_data(api.get_product(product["id"], PM))
    assert prod["on_hand_value_cents"] == 450
    assert prod["on_hand_qty"] == 4500
    assert finalized["cogs_cents"] != prod["on_hand_value_cents"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / per_line_then_sum_rounding_order
# Two weighed lines 33 c/lb x 1015 milli: rhu(33*1015/1000)=rhu(33.495)=33 each;
# per-line-then-sum => 66 (not rhu(66.99)=67).
# ---------------------------------------------------------------------------
def test_per_line_rounding_then_sum_subtotal(api):
    """PRD §2.5: "per-line monetary figures are each rounded before lines are
    summed (never summed first and rounded once) ..."
    PRD §3.7: "The `subtotal_cents` is the sum of the already-rounded `extended_price_cents` across all lines — lines are rounded individually and then summed, never summed and then rounded."

    Design: Difficulty/combinatorial_formula/per_line_then_sum_rounding_order
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_weighed_product(name="Loose Carrots", plu="4562",
                                              unit_price_cents=33, is_perishable=True,
                                              reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5000, unit_cost_cents=20,
                         expiration_date="2026-06-30T00:00:00Z",
                         expected_total_cents=100)
    sale = fixtures.open_sale()
    fixtures.add_weighed_line(sale["id"], product["id"], 1015)
    fixtures.add_weighed_line(sale["id"], product["id"], 1015)
    finalized = fixtures.finalize_sale(sale["id"])
    assert finalized["subtotal_cents"] == 66


def test_per_line_rounding_then_sum_total(api):
    """PRD §3.7: "The `total_cents` is the subtotal minus the coupon discount, floored at 0."
    PRD §2.5: "The phrase \"rounded half up\" means the fractional part of exactly
    one-half rounds away from zero to the next whole cent."

    Design: Difficulty/combinatorial_formula/per_line_then_sum_rounding_order
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_weighed_product(name="Loose Carrots 2", plu="4563",
                                              unit_price_cents=33, is_perishable=True,
                                              reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5000, unit_cost_cents=20,
                         expiration_date="2026-06-30T00:00:00Z",
                         expected_total_cents=100)
    sale = fixtures.open_sale()
    fixtures.add_weighed_line(sale["id"], product["id"], 1015)
    fixtures.add_weighed_line(sale["id"], product["id"], 1015)
    finalized = fixtures.finalize_sale(sale["id"])
    assert finalized["total_cents"] == 66


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / coupon_gate_keyed_on_subtotal_not_total
# subtotal 1000, coupon discount 150 min_spend 1000: gate on subtotal passes,
# discount 150, total 850.
# ---------------------------------------------------------------------------
def _setup_coupon_gate(api):
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    dept = fixtures.create_department()
    product = fixtures.create_product(department_id=dept["id"], name="Cereal",
                                      sku="SKU-CER", unit_price_cents=250,
                                      reorder_point_qty=0)
    coupon = fixtures.create_coupon(product["id"], code="CODE10", discount_cents=150,
                                    min_spend_cents=1000, stackable=False)
    member, clip = fixtures.create_member_with_clip(coupon["id"], email="a@x.com")
    fixtures.receive_lot(product["id"], 10, unit_cost_cents=100,
                         expected_total_cents=1000, override_variance=False)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 4, member_id=member["id"])
    return sale, clip


def test_coupon_gate_evaluated_against_subtotal(api):
    """PRD §3.7: "the `subtotal_cents` must be at least the coupon's `min_spend_cents`, and the stacking rule must hold ... The minimum-spend gate is tested against the pre-coupon subtotal, not the total."
    PRD §3.7: "When all of these hold, `coupon_discount_cents` is the smaller of the coupon's `discount_cents` and the subtotal ..."

    Design: Difficulty/combinatorial_formula/coupon_gate_keyed_on_subtotal_not_total
    """
    sale, clip = _setup_coupon_gate(api)
    finalized = fixtures.finalize_sale(sale["id"], clipped_coupon_id=clip["id"])
    assert finalized["subtotal_cents"] == 1000
    assert finalized["coupon_discount_cents"] == 150


def test_coupon_total_after_subtotal_gate(api):
    """PRD §3.7: "The transaction total is then assembled in a strictly pinned
    order: subtotal first, then the coupon gate against the subtotal, then the
    total."
    PRD §3.7: "The `total_cents` is the subtotal minus the coupon discount, floored at 0."

    Design: Difficulty/combinatorial_formula/coupon_gate_keyed_on_subtotal_not_total
    """
    sale, clip = _setup_coupon_gate(api)
    finalized = fixtures.finalize_sale(sale["id"], clipped_coupon_id=clip["id"])
    assert finalized["total_cents"] == 850


# ---------------------------------------------------------------------------
# Corner: calculations / fefo_orders_by_expiration_soonest_first
# lotB (06-15, rem4, cost70) received first, lotA (06-08, rem4, cost50) received
# second; sell 6 -> 4 from A + 2 from B -> cogs 4*50 + 2*70 = 340.
# ---------------------------------------------------------------------------
def test_fefo_orders_by_expiration_soonest_first(api):
    """PRD §3.8: "Eligible lots are consumed in order of soonest expiration first (lots with no expiration date sort last), then by earliest `created_at`."
    PRD §3.8: "for an each-sold product it is the units taken multiplied by the lot's `unit_cost_cents`. The accumulated figure becomes the sale's `cogs_cents`."

    Design: Corner/calculations/fefo_orders_by_expiration_soonest_first
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    dept = fixtures.create_department(name="Dairy")
    product = fixtures.create_product(department_id=dept["id"], name="Cheese",
                                      sku="SKU-CHZ", unit_price_cents=200,
                                      is_perishable=True, reorder_point_qty=0)
    # lotB received FIRST, expires later (06-15).
    fixtures.receive_lot(product["id"], 4, unit_cost_cents=70,
                         expiration_date="2026-06-15T00:00:00Z",
                         expected_total_cents=280)
    # lotA received SECOND, expires sooner (06-08) -> FEFO consumes it first.
    fixtures.receive_lot(product["id"], 4, unit_cost_cents=50,
                         expiration_date="2026-06-08T00:00:00Z",
                         expected_total_cents=200)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 6)
    finalized = fixtures.finalize_sale(sale["id"])
    assert finalized["cogs_cents"] == 340
    prod = get_success_data(api.get_product(product["id"], PM))
    assert prod["on_hand_qty"] == 2


# ---------------------------------------------------------------------------
# Corner: calculations / quarantined_lot_excluded_from_fefo_insufficient_stock
# ---------------------------------------------------------------------------
def test_quarantined_lot_excluded_from_fefo_insufficient_stock(api):
    """PRD §3.8: "quarantined lots and expired lots are not eligible even though quarantined lots still count toward `on_hand_qty`. This is why a finalize can be rejected for insufficient stock even when the product's on-hand quantity appears sufficient."

    Design: Corner/calculations/quarantined_lot_excluded_from_fefo_insufficient_stock
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="QStock", unit_price_cents=99, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100)
    lot = fixtures.get_single_lot(product["id"])
    get_success_data(api.quarantine_lot(lot["id"], AUD))
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 1)
    resp = api.finalize_sale(sale["id"], {}, CSH)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)
    prod = get_success_data(api.get_product(product["id"], PM))
    assert prod["on_hand_qty"] == 5


# ---------------------------------------------------------------------------
# Corner: validations / coupon_below_min_spend_not_redeemable
# ---------------------------------------------------------------------------
def test_coupon_below_min_spend_not_redeemable(api):
    """PRD §3.7: "the `subtotal_cents` must be at least the coupon's `min_spend_cents` ... if any condition fails, the finalize is rejected with `ERR_COUPON_NOT_REDEEMABLE`."

    Design: Corner/validations/coupon_below_min_spend_not_redeemable
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    dept = fixtures.create_department()
    product = fixtures.create_product(department_id=dept["id"], name="Min",
                                      sku="SKU-MIN", unit_price_cents=250,
                                      reorder_point_qty=0)
    coupon = fixtures.create_coupon(product["id"], code="MIN1000", discount_cents=50,
                                    min_spend_cents=1000, stackable=False)
    member, clip = fixtures.create_member_with_clip(coupon["id"], email="min@x.com")
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 2, member_id=member["id"])
    # subtotal 500 < min_spend 1000.
    resp = api.finalize_sale(sale["id"], {"clipped_coupon_id": clip["id"]}, CSH)
    validate_error(resp, ApiErrorId.ERR_COUPON_NOT_REDEEMABLE.value)


# ---------------------------------------------------------------------------
# Corner: consistency_model / finalize_changes_visible_in_same_response
# ---------------------------------------------------------------------------
def test_finalize_returns_computed_total_and_cogs_in_same_response(api):
    """PRD §3.7: "subtotal first, then the coupon gate against the subtotal, then
    the total."
    PRD §3.8: "The accumulated figure becomes the sale's `cogs_cents`."

    Design: Corner/consistency_model/finalize_changes_visible_in_same_response
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Imm", unit_price_cents=250, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 2)
    finalized = fixtures.finalize_sale(sale["id"])
    assert finalized["total_cents"] == 500
    assert finalized["cogs_cents"] == 200
