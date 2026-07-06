"""Pricing waterfall, delivery fee, redemption, and points-earn calculations."""
from test_helpers import (
    make_customer_headers,
    setup_store_item_slot_customer, create_store, create_menu_item, create_modifier,
    create_pickup_slot, create_customer, create_subscription_plan, create_active_subscription,
    create_cart_order, add_line, place, create_and_place_order, create_completed_order,
    seed_wallet, seed_points, get_order_line, get_loyalty_account,
)


def test_order_total_pinned_evaluation_order_delivery_ca(api):
    """PRD §3.5: "the `total_cents` is the residual minus `wallet_applied_cents`, floored at 0
    so it is never negative."
    PRD §3.5: "This ordering is pinned: wallet is applied after the points discount and after the
    delivery fee is added, never before, and the discount applies only to the subtotal — applying
    wallet first, or discounting the delivery fee, would yield a different and incorrect total."
    PRD §3.5: "a `DELIVERY` order has a fee equal to a base of 399 cents plus a surcharge equal
    to the `subtotal_cents` multiplied by the state's basis-point band and then divided by ten
    thousand, with that surcharge term rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/order_total_pinned_evaluation_order
    """
    store = create_store(state_code="CA", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Bowl1450", base_price_cents=1450, base_calories=600)
    slot = create_pickup_slot(store["id"], channel="DELIVERY")
    customer = create_customer(store["id"])
    seed_wallet(customer["id"], 500)
    seed_points(customer["loyalty_account_id"], 350)

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=2)
    placed = place(customer["id"], order["id"], slot["version"], points_redeemed=350)

    assert placed["subtotal_cents"] == 2900
    assert placed["delivery_fee_cents"] == 631
    assert placed["discount_cents"] == 300
    assert placed["wallet_applied_cents"] == 500
    assert placed["total_cents"] == 2731


def test_order_total_wallet_capped_at_residual(api):
    """PRD §3.5: "the `wallet_applied_cents` is the lesser of the customer's `wallet_credit_cents`
    and that residual."
    PRD §3.5: "the `total_cents` is the residual minus `wallet_applied_cents`, floored at 0 so it
    is never negative."

    Design: Difficulty/combinatorial_formula/order_total_pinned_evaluation_order
    """
    # COUNTER subtotal 1000, no discount, no fee -> residual 1000; wallet credit 5000 caps at 1000.
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Item1000", base_price_cents=1000, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])
    seed_wallet(customer["id"], 5000)

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=1)
    placed = place(customer["id"], order["id"], slot["version"], points_redeemed=0)

    assert placed["subtotal_cents"] == 1000
    assert placed["delivery_fee_cents"] == 0
    assert placed["wallet_applied_cents"] == 1000
    assert placed["total_cents"] == 0


def test_place_response_reflects_pricing_immediately(api):
    """PRD §3.5: "a `DELIVERY` order has a fee equal to a base of 399 cents plus a surcharge
    equal to the `subtotal_cents` multiplied by the state's basis-point band and then divided
    by ten thousand, with that surcharge term rounded half up to whole cents."
    PRD §3.5: "The order's `settlement_status` moves to `CAPTURED` and the charged amount equal
    to `total_cents` is recorded."

    Design: Corner/consistency_model/place_response_reflects_pricing_immediately
    """
    store = create_store(state_code="CA", throughput_capacity_per_slot=5)
    item = create_menu_item(store["id"], name="Bowl", base_price_cents=1450, base_calories=600)
    slot = create_pickup_slot(store["id"], channel="DELIVERY")
    customer = create_customer(store["id"])

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=2)
    placed = place(customer["id"], order["id"], slot["version"], points_redeemed=0)

    assert placed["subtotal_cents"] == 2900
    assert placed["delivery_fee_cents"] == 631
    assert placed["total_cents"] == 3531
    assert placed["settlement_status"] == "CAPTURED"


def test_delivery_fee_locker_not_waived_by_subscription(api):
    """PRD §3.5: "This waiver never touches the `LOCKER` flat fee, which is charged even under
    a free-delivery plan; a `COUNTER` order has no fee to waive in the first place."
    PRD §3.5: "a `LOCKER` order has a flat fee of 99 cents".

    Design: Corner/calculations/delivery_fee_locker_not_waived_by_subscription
    """
    store = create_store(state_code="CA", throughput_capacity_per_slot=5, locker_count=5)
    item = create_menu_item(store["id"], name="X", base_price_cents=500, base_calories=100)
    slot = create_pickup_slot(store["id"], channel="LOCKER")
    plan = create_subscription_plan(tier_name="FREEDEL", monthly_fee_cents=999, free_delivery=True)
    customer = create_customer(store["id"])
    sub = create_active_subscription(customer["id"], plan["id"])

    order = create_cart_order(customer["id"], store["id"], slot["id"], subscription_id=sub["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=1)
    placed = place(customer["id"], order["id"], slot["version"], points_redeemed=0)

    assert placed["delivery_fee_cents"] == 99
    assert placed["total_cents"] == 599


def test_redemption_value_partial_block_floored(api):
    """PRD §3.5: "points convert to cents in whole blocks of 100 points, partial blocks are
    dropped, so the number of usable blocks is `points_redeemed` divided by 100 with the
    remainder discarded, and the raw discount is that block count multiplied by 100 cents per
    block".

    Design: Corner/calculations/redemption_value_partial_block_floored
    """
    store, item, slot, customer = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})
    seed_points(customer["loyalty_account_id"], 150)

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=1)
    placed = place(customer["id"], order["id"], slot["version"], points_redeemed=150)

    assert placed["discount_cents"] == 100
    assert placed["total_cents"] == 400


def test_line_calories_per_unit_floored_at_zero(api):
    """PRD §3.4: "take the larger of that figure and 0 so a heavily-subtracted unit never goes
    negative, and multiply by `quantity` to obtain `line_calories`."

    Design: Corner/calculations/line_calories_per_unit_floored_at_zero
    """
    store = create_store()
    item = create_menu_item(store["id"], name="X", base_price_cents=500, base_calories=600)
    modifier = create_modifier(item["id"], name="LightCal", price_delta_cents=0, calorie_delta=-700)
    slot = create_pickup_slot(store["id"])
    customer = create_customer(store["id"])

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    line = add_line(customer["id"], order["id"], item["id"], quantity=2, modifier_ids=[modifier["id"]])

    assert line["line_calories"] == 0


def test_tier_gold_boundary_inclusive(api):
    """PRD §2.10: "A loyalty account's `tier` is `GREEN` when its `lifetime_points_earned` is
    below 5000, `GOLD` when it is at least 5000 but below 15000, and `PLATINUM` when it is at
    least 15000; the 5000 and 15000 boundaries belong to the higher tier, so exactly 5000
    lifetime points is `GOLD` and exactly 15000 is `PLATINUM`."
    PRD §3.3: "this appends a ledger entry, recomputes `points_balance`, and — only when
    `delta_points` is positive — recomputes `lifetime_points_earned` and the tier."

    Design: Corner/calculations/tier_gold_boundary_inclusive
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=5)
    customer = create_customer(store["id"])
    seed_points(customer["loyalty_account_id"], 5000)

    account = get_loyalty_account(customer["loyalty_account_id"])
    assert account["lifetime_points_earned"] == 5000
    assert account["tier"] == "GOLD"


def test_points_earned_base_no_subscription(api):
    """PRD §3.6: "The base earn is that eligible-cents figure divided by 10 and floored,
    granting one point per 10 cents of eligible spend."
    PRD §3.6: "with no active subscription the points earned equal the base points unchanged
    (equivalent to a 1.0× multiplier)."

    Design: Difficulty/dual_variant_calc/points_earned_base_vs_subscription_boost
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Bowl", base_price_cents=1450, base_calories=600)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    customer = create_customer(store["id"])

    done, _ = create_completed_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=2)

    assert done["points_earned"] == 290


def test_points_earned_subscription_boost(api):
    """PRD §3.6: "If the order applies a subscription whose `status` is `ACTIVE` at completion,
    the base points are then multiplied by the plan's `points_multiplier_bps` divided by ten
    thousand and floored again".

    Design: Difficulty/dual_variant_calc/points_earned_base_vs_subscription_boost
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=10)
    item = create_menu_item(store["id"], name="Bowl", base_price_cents=1450, base_calories=600)
    slot = create_pickup_slot(store["id"], channel="COUNTER")
    plan = create_subscription_plan(tier_name="PERKS_15", monthly_fee_cents=999,
                                    points_multiplier_bps=15000)
    customer = create_customer(store["id"])
    sub = create_active_subscription(customer["id"], plan["id"])

    done, _ = create_completed_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"],
        quantity=2, subscription_id=sub["id"])

    assert done["points_earned"] == 435
