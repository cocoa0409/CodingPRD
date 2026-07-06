"""Order pricing: provisional vs final variants, per-line rounding, discount base."""
from test_helpers import (
    validate_success, get_success_data,
    create_customer, create_product_with_lot, create_product, create_inventory_lot,
    create_order, create_order_with_line, add_line, submit_order, pay_order, record_cut,
    make_customer_headers, set_clock, create_coupon, TEST_USERS,
)


def test_provisional_total_uses_requested_yards(api):
    """PRD §3.4: "The provisional variant always uses requested_yards as the
    quantity for every line."

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_on_order
    """
    customer = create_customer()
    product, _ = create_product_with_lot(
        on_hand_yards=100, sell_mode="BY_YARD", unit_price_cents=350, min_cut_increment_yards=0.25
    )
    order, line = create_order_with_line(customer["id"], product["id"], requested_yards=2.5)
    submitted = submit_order(order["id"], customer["id"])
    # 350 * 2.5 = 875 rounded per line.
    assert submitted["provisional_total_cents"] == 875


def test_final_total_uses_actual_cut_yards(api):
    """PRD §3.4: "It computes final_total_cents using the final pricing variant,
    which differs from the provisional variant only in that by-the-yard lines use
    actual_cut_yards as the quantity while unit and bulk lines continue to use
    requested_yards"

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_on_order
    """
    customer = create_customer()
    product, _ = create_product_with_lot(
        on_hand_yards=100, sell_mode="BY_YARD", unit_price_cents=350, min_cut_increment_yards=0.25
    )
    order, line = create_order_with_line(customer["id"], product["id"], requested_yards=2.5)
    submit_order(order["id"], customer["id"])
    pay_order(order["id"], customer["id"])
    record_cut(line["id"], 2.75)
    resp = api.ready_order(order["id"], TEST_USERS["store_associate_headers"])
    data = validate_success(resp)
    # 350 * 2.75 = 962.5 -> round_half_up 963.
    assert data["final_total_cents"] == 963
    assert data["provisional_total_cents"] == 875


def test_round_per_line_then_sum_provisional(api):
    """PRD §2.5: "per-line prices are each rounded to whole cents before any
    summation, and coupon discounts are computed and rounded step by step"

    Design: Difficulty/combinatorial_formula/order_pricing_round_per_line_then_sum
    """
    customer = create_customer()
    product = create_product(sell_mode="BY_YARD", unit_price_cents=333, min_cut_increment_yards=0.5)
    create_inventory_lot(product["id"], on_hand_yards=100)
    order = create_order(customer["id"])
    add_line(order["id"], customer["id"], product["id"], requested_yards=1.5)
    add_line(order["id"], customer["id"], product["id"], requested_yards=2.5)
    submitted = submit_order(order["id"], customer["id"])
    # 333*1.5=499.5->500 ; 333*2.5=832.5->833 ; sum=1333 (not 1332).
    assert submitted["provisional_total_cents"] == 1333


def test_round_per_line_individual_line_subtotals(api):
    """PRD §3.4: "the raw amount is the product's unit_price_cents times the line
    quantity, and this is rounded half up to whole cents to yield
    line_subtotal_cents; those already-rounded line values are then summed into
    the subtotal."

    Design: Difficulty/combinatorial_formula/order_pricing_round_per_line_then_sum
    """
    customer = create_customer()
    product = create_product(sell_mode="BY_YARD", unit_price_cents=333, min_cut_increment_yards=0.5)
    create_inventory_lot(product["id"], on_hand_yards=100)
    order = create_order(customer["id"])
    add_line(order["id"], customer["id"], product["id"], requested_yards=1.5)
    add_line(order["id"], customer["id"], product["id"], requested_yards=2.5)
    submit_order(order["id"], customer["id"])
    lines_resp = api.list_order_lines_by_order(order["id"], make_customer_headers(customer["id"]))
    lines = get_success_data(lines_resp)
    subtotals = sorted(l["line_subtotal_cents"] for l in lines)
    assert subtotals == [500, 833]


def test_percent_coupon_excludes_clearance_base(api):
    """PRD §3.3: "For a PERCENT coupon, the base is the running amount minus the
    clearance subtotal when the coupon excludes clearance, or the full running
    amount otherwise; the step discount is that base multiplied by the coupon's
    value, rounded half up to whole cents."

    Design: Corner/calculations/percent_coupon_excludes_clearance_base
    """
    set_clock("2026-06-01T00:00:00Z")
    customer = create_customer()
    clr = create_product(sell_mode="UNIT", unit_price_cents=1000, is_clearance=True)
    reg = create_product(sell_mode="UNIT", unit_price_cents=1000, is_clearance=False)
    create_inventory_lot(clr["id"], on_hand_yards=50)
    create_inventory_lot(reg["id"], on_hand_yards=50)
    coupon = create_coupon(discount_type="PERCENT", value=0.1, excludes_clearance=True, priority=1)
    order = create_order(customer["id"])
    add_line(order["id"], customer["id"], clr["id"], requested_yards=1)
    add_line(order["id"], customer["id"], reg["id"], requested_yards=1)
    apply_resp = api.apply_coupon(
        order["id"],
        {"code": coupon["code"], "expected_order_version": order["version"]},
        make_customer_headers(customer["id"]),
    )
    validate_success(apply_resp)
    submitted = submit_order(order["id"], customer["id"])
    # base excludes 1000 clearance -> 10% of 1000 = 100 discount; 2000 - 100 = 1900.
    assert submitted["provisional_total_cents"] == 1900
