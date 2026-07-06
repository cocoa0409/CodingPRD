"""Box charge computation: subtotal, free-ship branch, nested-min credit, referee discount.

Translates the combinatorial-formula difficulty instances (queue A) plus corner calculation and
consistency instances (queue B).
"""
from test_helpers import (
    validate_success, make_admin_headers,
    simulate_payment_payload,
    setup_pro_box_locked, setup_pro_box_ready_to_lock, setup_referee_box_ready_two_lines,
)

ADMIN = make_admin_headers()


def test_box_charge_nested_min_credit_and_free_ship_branch(api):
    """PRD §3.5: "The `subtotal_cents` is the box's `plan_price_per_meal_cents` multiplied by
    that meal count." "The `shipping_fee_cents` is zero when the meal count is greater than or
    equal to the free-shipping threshold of 12 meals (`FREE_SHIP_MIN_MEALS`), and otherwise is
    the box's snapshotted `base_shipping_fee_cents`." "The `credit_applied_cents` is the smaller
    of the gross and the customer's `wallet_credit_cents` at lock time, so it never exceeds
    either the gross or the available wallet balance." "The `total_charged_cents` is the gross
    minus the `credit_applied_cents`."

    Design: Difficulty/combinatorial_formula/box_charge_nested_min_credit_and_shipping_branch_mode_a
    """
    ctx = setup_pro_box_locked(api, quantity=12, wallet_cents=2000)  # PENDING, wallet 2000
    box = validate_success(
        api.simulate_payment(simulate_payment_payload(ctx["box_id"], "SUCCEEDED"), ADMIN), 200)
    assert box["subtotal_cents"] == 13188
    assert box["shipping_fee_cents"] == 0
    assert box["cold_pack_fee_cents"] == 500
    assert box["credit_applied_cents"] == 2000
    assert box["total_charged_cents"] == 11688


def test_box_charge_credit_consumed_from_wallet_on_charge(api):
    """PRD §3.5: "When the `outcome` is `SUCCEEDED`, billing moves `PENDING → CHARGED`; at that
    moment the pinned `credit_applied_cents` is consumed from the wallet by appending a negative
    `CREDIT_APPLIED` ledger entry of that amount (written only when `credit_applied_cents` is
    greater than zero)."

    Design: Difficulty/combinatorial_formula/box_charge_nested_min_credit_and_shipping_branch_mode_a
    """
    ctx = setup_pro_box_locked(api, quantity=12, wallet_cents=2000)
    validate_success(
        api.simulate_payment(simulate_payment_payload(ctx["box_id"], "SUCCEEDED"), ADMIN), 200)
    customer = validate_success(api.get_customer(ctx["cust_id"], ADMIN), 200)
    assert customer["wallet_credit_cents"] == 0, "the applied 2000c credit is consumed at charge"


def test_referee_first_box_discount_round_per_line_then_sum(api):
    """PRD §3.5: "for each `SELECTED` item, take that line's gross (the box's
    `plan_price_per_meal_cents` times the line `quantity`), multiply it by the referee discount
    rate of 15 percent (`REFEREE_DISCOUNT_PCT` = 0.15), and round that single line's result to
    whole cents using round-half-up; then sum the rounded per-line discounts."

    Design: Difficulty/combinatorial_formula/referee_first_box_discount_round_per_line_then_sum_mode_b
    """
    ctx = setup_referee_box_ready_two_lines(api)  # two SELECTED lines of qty 3 (1099c each meal)
    box = validate_success(api.lock_box(ctx["box_id"], ADMIN), 200)
    # line_gross 3297c * 0.15 = 494.55 -> 495c per line; two lines -> 990c (sum-then-round = 989c)
    assert box["subtotal_cents"] == 6594
    assert box["discount_cents"] == 990


def test_referee_first_box_discount_total_and_shipping(api):
    """PRD §3.5: "The gross amount is the `subtotal_cents` minus the `discount_cents` plus the
    `shipping_fee_cents` plus the `cold_pack_fee_cents`". "The `shipping_fee_cents` is zero when
    the meal count is greater than or equal to the free-shipping threshold of 12 meals
    (`FREE_SHIP_MIN_MEALS`), and otherwise is the box's snapshotted `base_shipping_fee_cents`."

    Design: Difficulty/combinatorial_formula/referee_first_box_discount_round_per_line_then_sum_mode_b
    """
    ctx = setup_referee_box_ready_two_lines(api)  # 6 meals total, below the free-ship threshold
    box = validate_success(api.lock_box(ctx["box_id"], ADMIN), 200)
    assert box["shipping_fee_cents"] == 1000  # 6 < 12 -> base shipping applies
    # gross = 6594 - 990 + 1000 + 500 (cold pack) = 7104, wallet 0 -> total = gross
    assert box["total_charged_cents"] == 7104


def test_free_ship_below_threshold_charges_base_shipping(api):
    """PRD §3.5: "The `shipping_fee_cents` is zero when the meal count is greater than or equal
    to the free-shipping threshold of 12 meals (`FREE_SHIP_MIN_MEALS`), and otherwise is the
    box's snapshotted `base_shipping_fee_cents`."

    Design: Corner/calculations/free_ship_below_threshold_charges_base_shipping
    """
    ctx = setup_pro_box_ready_to_lock(api, quantity=11)  # 11 < 12 -> base shipping applies
    validate_success(api.lock_box(ctx["box_id"], ADMIN), 200)
    box = validate_success(
        api.simulate_payment(simulate_payment_payload(ctx["box_id"], "SUCCEEDED"), ADMIN), 200)
    assert box["subtotal_cents"] == 12089  # 11 * 1099
    assert box["shipping_fee_cents"] == 1000
    assert box["total_charged_cents"] == 13589  # 12089 + 1000 + 500 cold pack


def test_charge_fields_visible_immediately_after_lock(api):
    """PRD §3.5: "Locking moves fulfillment `OPEN → LOCKED`, computes and pins the box's charge
    fields, and moves billing `UNCHARGED → PENDING`."

    Design: Corner/consistency_model/immediate_charge_fields_visible_after_lock
    """
    ctx = setup_pro_box_ready_to_lock(api, quantity=12)
    box = validate_success(api.lock_box(ctx["box_id"], ADMIN), 200)
    assert box["subtotal_cents"] == 13188
    assert box["billing_status"] == "PENDING"
    assert box["fulfillment_status"] == "LOCKED"
