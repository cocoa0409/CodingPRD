"""Order lines and placement pricing: per-unit rounding order, the
provisional-vs-final subtotal split, quantity-floor validation, bundle-component
matching, and the inventory-coverage boundary.
"""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    new_customer, new_gold_customer, new_product, new_lot, new_bundle,
    new_order, add_line, place, fulfill, recall_lot, make_customer_headers,
)

OPERATOR = TEST_USERS["store_operator_headers"]


def test_bundled_line_net_unit_price_rounded_per_unit(api):
    """PRD §3.6: "The `net_unit_price_cents` is the `gross_unit_price_cents`
    multiplied by one minus the bundle discount and then by one minus the
    applicable purchase discount, rounded half-up to a whole cent at the per-unit
    level before any multiplication by quantity."

    Design: Difficulty/combinatorial_formula/order_line_pricing_per_unit_rounding
    """
    cust = new_gold_customer(email="g2@x.com", full_name="Gold Two")
    prod = new_product(unit_price_cents=1999, form="GUMMY", regimen_goals=["ENERGY"])
    new_lot(prod["id"], quantity_received=100, lot_number="RD-1")
    bundle = new_bundle([prod["id"]], discount_pct=0.15, name="Round Stack")
    order = new_order(cust["id"])
    line = add_line(order["id"], cust["id"], prod["id"], 3, bundle_id=bundle["id"])
    place(order["id"], cust["id"])
    fetched = validate_success(api.get_order_line(line["id"], OPERATOR), 200)
    # round_half_up(1999 * 0.85 * 0.90) = round_half_up(1529.235) = 1529
    assert fetched["net_unit_price_cents"] == 1529


def test_bundled_line_total_is_rounded_unit_times_quantity(api):
    """PRD §2.5: "per-unit discounted prices are rounded to whole cents *before*
    being multiplied by a line quantity, not after."
    PRD §3.6: "The `line_total_cents` is then `net_unit_price_cents` multiplied by
    the line's `quantity`."

    Design: Difficulty/combinatorial_formula/order_line_pricing_per_unit_rounding
    """
    cust = new_gold_customer(email="g2@x.com", full_name="Gold Two")
    prod = new_product(unit_price_cents=1999, form="GUMMY", regimen_goals=["ENERGY"])
    new_lot(prod["id"], quantity_received=100, lot_number="RD-1")
    bundle = new_bundle([prod["id"]], discount_pct=0.15, name="Round Stack")
    order = new_order(cust["id"])
    line = add_line(order["id"], cust["id"], prod["id"], 3, bundle_id=bundle["id"])
    place(order["id"], cust["id"])
    fetched = validate_success(api.get_order_line(line["id"], OPERATOR), 200)
    # 1529 per unit * 3 = 4587 (differs from rounding the line total after multiply).
    assert fetched["line_total_cents"] == 4587


def test_provisional_subtotal_captured_at_placement(api):
    """PRD §3.6: "The order's `provisional_subtotal_cents` is the sum of
    `line_total_cents` across all lines, captured at placement when every line is
    fully allocated and no line is short."

    Design: Difficulty/dual_variant_calc/order_provisional_vs_final_subtotal
    """
    cust = new_gold_customer(email="g1@x.com", full_name="Gold One")
    prod = new_product(unit_price_cents=5000)
    new_lot(prod["id"], quantity_received=2, lot_number="PF-1")
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 2)
    placed = place(order["id"], cust["id"])
    # GOLD one-off: net_unit = round_half_up(5000 * 0.90) = 4500; * 2 = 9000.
    assert placed["provisional_subtotal_cents"] == 9000


def test_final_subtotal_drops_to_zero_when_recall_shorts_line(api):
    """PRD §3.6: "The order's `final_subtotal_cents` is recomputed as the sum over
    lines of `net_unit_price_cents` multiplied by the line's `quantity` minus its
    `short_quantity`; a recall that shorted a line between placement and
    fulfilment makes the final subtotal fall below the provisional one"

    Design: Difficulty/dual_variant_calc/order_provisional_vs_final_subtotal
    """
    cust = new_gold_customer(email="g1@x.com", full_name="Gold One")
    prod = new_product(unit_price_cents=5000)
    lot = new_lot(prod["id"], quantity_received=2, lot_number="PF-1")
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 2)
    place(order["id"], cust["id"])
    recall_lot(lot["id"], reason="contamination", severity="CLASS_I")
    fulfilled = fulfill(order["id"])
    assert fulfilled["final_subtotal_cents"] == 0


def test_add_line_zero_quantity_rejected(api):
    """PRD §3.6: "The `quantity` must be at least 1; a quantity below 1 is
    rejected with `ERR_INVALID_QUANTITY`."

    Design: Difficulty/boundary_precision_check/zero_quantity_line_boundary
    """
    cust = new_customer(email="c10@x.com", full_name="Cust Ten")
    prod = new_product(unit_price_cents=1000)
    order = new_order(cust["id"])
    res = api.create_order_line(order["id"], {"product_id": prod["id"], "quantity": 0},
                                make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_QUANTITY", expected_status=422)


def test_add_line_quantity_one_accepted(api):
    """PRD §3.6: "The `quantity` must be at least 1; a quantity below 1 is
    rejected with `ERR_INVALID_QUANTITY`."

    Design: Difficulty/boundary_precision_check/zero_quantity_line_boundary
    """
    cust = new_customer(email="c10@x.com", full_name="Cust Ten")
    prod = new_product(unit_price_cents=1000)
    order = new_order(cust["id"])
    res = api.create_order_line(order["id"], {"product_id": prod["id"], "quantity": 1},
                                make_customer_headers(cust["id"]))
    line = validate_success(res, 201)
    assert line["quantity"] == 1


def test_line_with_bundle_id_of_noncomponent_rejected(api):
    """PRD §3.6: "If a `bundle_id` is supplied, the line's product must be a
    component of that bundle; otherwise the line is rejected with
    `ERR_BUNDLE_PRODUCT_MISMATCH`."

    Design: Corner/validations/corner_bundle_product_mismatch_rejected
    """
    cust = new_customer(email="v2@x.com", full_name="V Two")
    prod_x = new_product(unit_price_cents=1000, name="Bundle X")
    prod_y = new_product(unit_price_cents=1000, name="Bundle Y", regimen_goals=["ENERGY"])
    bundle = new_bundle([prod_x["id"]], discount_pct=0.10, name="X Stack")
    order = new_order(cust["id"])
    res = api.create_order_line(
        order["id"], {"product_id": prod_y["id"], "quantity": 1, "bundle_id": bundle["id"]},
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_BUNDLE_PRODUCT_MISMATCH", expected_status=422)


def test_place_line_for_exactly_available_units_succeeds(api):
    """PRD §3.6: "Inventory must fully cover every line (below), or the placement
    is rejected with `ERR_INSUFFICIENT_INVENTORY`."

    Design: Difficulty/boundary_precision_check/inventory_exact_available_boundary
    """
    cust = new_customer(email="c9@x.com", full_name="Cust Nine")
    prod = new_product(unit_price_cents=1000)
    new_lot(prod["id"], quantity_received=10, lot_number="BD-1")
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 10)
    placed = place(order["id"], cust["id"])
    assert placed["status"] == "PLACED"


def test_place_line_exceeding_available_units_rejected(api):
    """PRD §3.6: "If the candidate pool is exhausted while demand remains, the
    entire order is rejected with `ERR_INSUFFICIENT_INVENTORY` and no allocation
    from this placement persists."

    Design: Difficulty/boundary_precision_check/inventory_exact_available_boundary
    """
    cust = new_customer(email="c9@x.com", full_name="Cust Nine")
    prod = new_product(unit_price_cents=1000)
    new_lot(prod["id"], quantity_received=10, lot_number="BD-1")
    # Exhaust the first lot's available units via a placed order.
    order_ok = new_order(cust["id"])
    add_line(order_ok["id"], cust["id"], prod["id"], 10)
    place(order_ok["id"], cust["id"])
    # A fresh 10-unit lot exists; total available is now 10, but the line needs 11.
    new_lot(prod["id"], quantity_received=10,
            expiration_date="2027-02-01T00:00:00Z", lot_number="BD-2")
    order_bad = new_order(cust["id"])
    add_line(order_bad["id"], cust["id"], prod["id"], 11)
    res = api.place_order(order_bad["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INSUFFICIENT_INVENTORY", expected_status=409)
