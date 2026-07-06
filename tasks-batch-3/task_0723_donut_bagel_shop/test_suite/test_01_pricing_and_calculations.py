"""Tiered pricing, wholesale sum-then-round, markdown, reward, and deposit/bulk
boundaries — the pricing-engine calculations of the shop."""
import pytest

from test_helpers import (
    api_client as _ac,
    validate_success,
    TEST_USERS,
    line_item, wholesale_line,
    setup_selling_day_with_baked_batch,
    setup_account_with_standing_order,
    create_production_day,
    create_product, create_wholesale_account, create_standing_order,
    schedule_delivery, create_cart, create_paid_order, create_loyalty_account,
    create_pre_order,
)

ADMIN = TEST_USERS["shop_admin_headers"]
CASHIER = TEST_USERS["cashier_headers"]


# =====================================================================
# Difficulty/combinatorial_formula/line_price_tiered_bulk_vs_dozen_selection  (2)
# =====================================================================
def test_line_price_dozen_plus_remainder_qty13(api):
    """PRD §3.4: "the line is priced by splitting the quantity into whole dozens
    and a remainder: the number of complete dozens (the quantity divided by twelve,
    discarding any remainder) is multiplied by dozen_price_cents, and the leftover
    units (the quantity modulo twelve) are each priced at unit_price_cents; the line
    total is the sum of those two parts."

    Design: Difficulty/combinatorial_formula/line_price_tiered_bulk_vs_dozen_selection
    """
    day, product, _batch = setup_selling_day_with_baked_batch("GLAZED", par_qty=40)
    order = create_cart(day["id"], [line_item(product["id"], 13)])
    assert order["subtotal_cents"] == 1650, (
        f"qty 13 GLAZED = 1*1500 + 1*150; got {order['subtotal_cents']}")


def test_line_price_flat_bulk_at_threshold_qty24(api):
    """PRD §3.4: "if the line quantity is at or above the product's bulk_threshold —
    the boundary is inclusive — the whole line is priced at the quantity multiplied
    by bulk_unit_price_cents, and the dozen tier does not apply at all."

    Design: Difficulty/combinatorial_formula/line_price_tiered_bulk_vs_dozen_selection
    """
    day, product, _batch = setup_selling_day_with_baked_batch("GLAZED", par_qty=40)
    order = create_cart(day["id"], [line_item(product["id"], 24)])
    assert order["subtotal_cents"] == 2640, (
        f"qty 24 GLAZED = 24*110 flat bulk; got {order['subtotal_cents']}")


# =====================================================================
# Difficulty/boundary_precision_check/bulk_threshold_inclusive_24_vs_23  (2)
# =====================================================================
def test_bulk_threshold_below_boundary_qty23_uses_dozen(api):
    """PRD §3.4: "if the line quantity is at or above the product's bulk_threshold —
    the boundary is inclusive — the whole line is priced at the quantity multiplied
    by bulk_unit_price_cents, and the dozen tier does not apply at all. Otherwise the
    line is priced by splitting the quantity into whole dozens and a remainder."

    Design: Difficulty/boundary_precision_check/bulk_threshold_inclusive_24_vs_23
    """
    day, product, _batch = setup_selling_day_with_baked_batch("GLAZED", par_qty=60)
    order = create_cart(day["id"], [line_item(product["id"], 23)])
    assert order["subtotal_cents"] == 3150, (
        f"qty 23 = 1*1500 + 11*150 = 3150; got {order['subtotal_cents']}")


def test_bulk_threshold_at_boundary_qty24_flips_to_bulk(api):
    """PRD §3.4: "if the line quantity is at or above the product's bulk_threshold —
    the boundary is inclusive — the whole line is priced at the quantity multiplied
    by bulk_unit_price_cents, and the dozen tier does not apply at all."

    Design: Difficulty/boundary_precision_check/bulk_threshold_inclusive_24_vs_23
    """
    day, product, _batch = setup_selling_day_with_baked_batch("GLAZED", par_qty=60)
    order = create_cart(day["id"], [line_item(product["id"], 24)])
    assert order["subtotal_cents"] == 2640, (
        f"qty 24 = 24*110 = 2640; got {order['subtotal_cents']}")


# =====================================================================
# Difficulty/dual_variant_calc/wholesale_amount_sum_then_round_vs_per_line_round (2)
# Difficulty/combinatorial_formula/wholesale_amount_nested_rounding_order_pinned (2)
# Both pin amount_cents == 242 from GLAZED q1 + EVERYTHING q1 at discount 0.15.
# =====================================================================
def _schedule_two_line_delivery():
    account, so, _products = setup_account_with_standing_order(
        [("GLAZED", 1), ("EVERYTHING", 1)], discount_pct=0.15, credit_limit_cents=100000)
    day = create_production_day()
    delivery = schedule_delivery(day["id"], so["id"],
                                 "2027-06-02T08:00:00Z", "2027-06-02T09:00:00Z")
    return delivery


def test_wholesale_amount_sum_then_round_equals_242(api):
    """PRD §3.7: "two lines with raw prices 150 and 135 under a 0.15 discount yield
    round-half-up of 285 times 0.85, which is round-half-up of 242.25, namely 242 —
    whereas discounting and rounding line by line would give 128 plus 115, namely 243.
    The summed-then-rounded figure is the contract."

    Design: Difficulty/dual_variant_calc/wholesale_amount_sum_then_round_vs_per_line_round
    """
    delivery = _schedule_two_line_delivery()
    assert delivery["amount_cents"] == 242, (
        f"sum-then-round(285*0.85)=242; got {delivery['amount_cents']}")
    assert delivery["status"] == "SCHEDULED"


def test_wholesale_amount_computed_at_release_status_scheduled(api):
    """PRD §3.7: "its amount_cents is computed at release (see below). A released
    delivery enters status SCHEDULED."

    Design: Difficulty/dual_variant_calc/wholesale_amount_sum_then_round_vs_per_line_round
    """
    delivery = _schedule_two_line_delivery()
    assert delivery["status"] == "SCHEDULED"
    assert delivery["amount_cents"] == 242, (
        f"amount computed at release = sum-then-round(285*0.85) = 242; "
        f"got {delivery['amount_cents']}")


def test_wholesale_amount_rounding_order_pinned_to_sum_first(api):
    """PRD §3.7: "Apply the account's discount to that single summed total — multiply
    the raw sum by one minus discount_pct — and round the result half up to whole
    cents. This sum-then-round order is mandatory and is not equivalent to rounding
    each discounted line and summing."

    Design: Difficulty/combinatorial_formula/wholesale_amount_nested_rounding_order_pinned
    """
    delivery = _schedule_two_line_delivery()
    assert delivery["amount_cents"] == 242, (
        f"sum-then-round must yield 242 (per-line-then-sum would be 243); "
        f"got {delivery['amount_cents']}")


def test_wholesale_amount_frozen_value_survives_to_invoice(api):
    """PRD §3.7: "The invoice amount is computed once, at release, and frozen at invoice."

    Design: Difficulty/combinatorial_formula/wholesale_amount_nested_rounding_order_pinned
    """
    account, so, _products = setup_account_with_standing_order(
        [("GLAZED", 1), ("EVERYTHING", 1)], discount_pct=0.15, credit_limit_cents=100000)
    day = create_production_day()
    driver = TEST_USERS["route_driver_headers"]
    delivery = schedule_delivery(day["id"], so["id"],
                                 "2027-06-04T08:00:00Z", "2027-06-04T09:00:00Z")
    validate_success(_ac.pick_delivery(day["id"], delivery["id"], driver))
    validate_success(_ac.deliver_delivery(day["id"], delivery["id"], driver))
    invoiced = validate_success(_ac.invoice_delivery(day["id"], delivery["id"], ADMIN))
    assert invoiced["amount_cents"] == 242, (
        f"the release-time sum-then-round figure (242) is frozen at invoice; "
        f"got {invoiced['amount_cents']}")


# =====================================================================
# Corner/calculations/markdown_price_rounding_half_up  (1)
# =====================================================================
def test_markdown_price_round_half_up_sesame(api):
    """PRD §3.5: "The markdown price of a product is its unit_price_cents reduced by
    forty percent, rounded half up to whole cents — equivalently, sixty percent of the
    unit price, rounded half up. For example, a unit price of 150 cents yields a
    markdown price of 90 cents, and 175 cents yields 105 cents."

    Design: Corner/calculations/markdown_price_rounding_half_up
    """
    day, product, batch = setup_selling_day_with_baked_batch("SESAME", par_qty=30)
    validate_success(_ac.markdown_batch(day["id"], batch["id"], CASHIER))
    order = create_cart(day["id"], [line_item(product["id"], 4, marked_down=True)])
    assert order["subtotal_cents"] == 288, (
        f"round_half_up(120*0.6)=72; 72*4=288; got {order['subtotal_cents']}")


# =====================================================================
# Corner/calculations/reward_redemption_caps_discount_at_subtotal  (1)
# =====================================================================
def test_reward_redemption_caps_discount_and_total(api):
    """PRD §3.4: "when redemption applies, the discount is the smaller of the reward
    value (1200 cents) and the subtotal, so the discount never exceeds what is owed.
    The order total_cents is the subtotal minus the loyalty discount, floored at zero."

    Design: Corner/calculations/reward_redemption_caps_discount_at_subtotal
    """
    day, product, _batch = setup_selling_day_with_baked_batch("GLAZED", par_qty=140)
    loyalty = create_loyalty_account()
    # Prior 120-GLAZED PAID order accrues 10 punches -> one 1200-cent reward.
    create_paid_order(day["id"], [line_item(product["id"], 120)],
                      loyalty_account_id=loyalty["id"])
    # New order subtotal 1650 (qty 13 = 1500+150) with reward redeemed.
    paid = create_paid_order(day["id"], [line_item(product["id"], 13)],
                             loyalty_account_id=loyalty["id"], redeem_reward=True)
    assert paid["loyalty_discount_cents"] == 1200, (
        f"discount = min(1200, 1650) = 1200; got {paid['loyalty_discount_cents']}")
    assert paid["total_cents"] == 450, (
        f"total = 1650 - 1200 = 450; got {paid['total_cents']}")


# =====================================================================
# Difficulty/boundary_precision_check/catering_deposit_threshold_inclusive_subtotal (2)
# =====================================================================
def test_catering_deposit_at_threshold_subtotal_4050(api):
    """PRD §3.8: "if the subtotal is at or above the catering deposit threshold of
    4050 cents — the boundary is inclusive — the deposit_due_cents is twenty-five
    percent of the subtotal, rounded half up; otherwise deposit_due_cents is zero.
    Thus a subtotal of exactly 4050 cents requires a deposit of 1013 cents
    (round-half-up of 4050 times 0.25)."

    Design: Difficulty/boundary_precision_check/catering_deposit_threshold_inclusive_subtotal
    """
    glazed = create_product("GLAZED")
    sesame = create_product("SESAME")
    every = create_product("EVERYTHING")
    account = create_wholesale_account(name="Party Co", discount_pct=0.10)
    day = create_production_day()
    # G23 (1500+11*150=3150) + S3 (3*120=360) + E4 (4*135=540) = 4050.
    pre = create_pre_order(
        account["id"], day["id"], "2027-07-01T07:00:00Z", "2027-07-01T08:00:00Z",
        [wholesale_line(glazed["id"], 23), wholesale_line(sesame["id"], 3),
         wholesale_line(every["id"], 4)])
    assert pre["subtotal_cents"] == 4050, f"got {pre['subtotal_cents']}"
    assert pre["deposit_due_cents"] == 1013, (
        f"round_half_up(4050*0.25)=1013; got {pre['deposit_due_cents']}")


def test_catering_deposit_below_threshold_subtotal_4035_zero(api):
    """PRD §3.8: "otherwise deposit_due_cents is zero. ... while a subtotal of 4035
    cents — one reachable step below the threshold — requires no deposit at all."

    Design: Difficulty/boundary_precision_check/catering_deposit_threshold_inclusive_subtotal
    """
    glazed = create_product("GLAZED")
    sesame = create_product("SESAME")
    every = create_product("EVERYTHING")
    account = create_wholesale_account(name="Party Co", discount_pct=0.10)
    day = create_production_day()
    # G23 (3150) + S4 (480) + E3 (405) = 4035.
    pre = create_pre_order(
        account["id"], day["id"], "2027-07-01T09:00:00Z", "2027-07-01T10:00:00Z",
        [wholesale_line(glazed["id"], 23), wholesale_line(sesame["id"], 4),
         wholesale_line(every["id"], 3)])
    assert pre["subtotal_cents"] == 4035, f"got {pre['subtotal_cents']}"
    assert pre["deposit_due_cents"] == 0, (
        f"subtotal 4035 < 4050 threshold -> deposit 0; got {pre['deposit_due_cents']}")
