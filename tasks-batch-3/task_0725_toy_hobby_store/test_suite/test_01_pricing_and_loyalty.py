"""Order pricing (provisional vs final) and loyalty point accrual."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_customer_headers,
    create_active_product, create_store, create_inventory, create_customer,
    create_open_order, add_line,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
ANY = TEST_USERS["any_headers"]


def _warm_up_to_gold(api, customer_id, store_id, product_id):
    """Fulfill a qty-500 (msrp 1000) order at BRONZE -> 5000 points -> GOLD."""
    o = create_open_order(customer_id, store_id)
    add_line(o["id"], customer_id, product_id, qty=500, recipient_age_months=60)
    get_success_data(api.submit_order(o["id"], make_customer_headers(customer_id)))
    get_success_data(api.mark_ready_order(o["id"], ASSOCIATE))
    get_success_data(api.pay_order(o["id"], {"amount_cents": 500000}, ASSOCIATE))
    get_success_data(api.fulfill_order(o["id"], ASSOCIATE))


def test_final_discount_reflects_tier_promoted_after_submit(api):
    """PRD §3.6: "When the order is marked ready, `pricing_variant` locks to `FINAL`
    and the discount is recomputed against the customer's `loyalty_tier` as read at
    mark-ready time — so if the tier changed between submit and mark-ready, the final
    discount can differ from the provisional one."

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_on_tier_change
    """
    product = create_active_product(msrp_cents=1000, is_exclusive=False)
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=600)
    customer = create_customer()
    cid = customer["id"]

    order = create_open_order(cid, store["id"])
    add_line(order["id"], cid, product["id"], qty=10, recipient_age_months=60)
    get_success_data(api.submit_order(order["id"], make_customer_headers(cid)))

    # Promote to GOLD after submit but before mark-ready.
    _warm_up_to_gold(api, cid, store["id"], product["id"])

    data = validate_success(api.mark_ready_order(order["id"], ASSOCIATE))
    assert data["pricing_variant"] == "FINAL"
    assert data["discount_cents"] == 1000, f"expected FINAL GOLD discount 1000, got {data['discount_cents']}"
    assert data["total_cents"] == 9000


def test_provisional_discount_uses_tier_at_submit(api):
    """PRD §3.6: "Provisional pricing reflects the tier and lines as of submit and is
    recomputed if lines change before the order becomes ready; `pricing_variant` stays
    `PROVISIONAL`."
    PRD §3.6: "The per-line loyalty discount depends on the customer's tier: `BRONZE`
    earns no discount, `SILVER` earns 5 percent, and `GOLD` earns 10 percent."

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_on_tier_change
    """
    product = create_active_product(msrp_cents=1000, is_exclusive=False)
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=600)
    customer = create_customer()
    cid = customer["id"]

    order = create_open_order(cid, store["id"])
    add_line(order["id"], cid, product["id"], qty=10, recipient_age_months=60)
    data = validate_success(api.submit_order(order["id"], make_customer_headers(cid)))
    assert data["pricing_variant"] == "PROVISIONAL"
    assert data["discount_cents"] == 0, "BRONZE customer earns no discount at submit"
    assert data["total_cents"] == 10000


def test_final_earn_persisted_at_fulfill_for_gold_customer(api):
    """PRD §3.8: "The base is `total_cents` divided by 100 and rounded down to a whole
    number."
    PRD §3.8: "That base is multiplied by the tier multiplier — 1.0 for `BRONZE`, 1.5 for
    `SILVER`, and 2.0 for `GOLD` — and the product is rounded down to whole points to give
    the points earned, which are added to the customer's `lifetime_points`."

    Design: Difficulty/dual_variant_calc/loyalty_points_estimate_vs_final_earn
    """
    product = create_active_product(msrp_cents=1000, is_exclusive=False)
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=600)
    customer = create_customer()
    cid = customer["id"]

    # Promote to GOLD (lifetime 5000).
    _warm_up_to_gold(api, cid, store["id"], product["id"])

    # Order O: total 9000 at GOLD (discount 1000 off 10000).
    order = create_open_order(cid, store["id"])
    add_line(order["id"], cid, product["id"], qty=10, recipient_age_months=60)
    get_success_data(api.submit_order(order["id"], make_customer_headers(cid)))
    ready = validate_success(api.mark_ready_order(order["id"], ASSOCIATE))
    assert ready["total_cents"] == 9000
    get_success_data(api.pay_order(order["id"], {"amount_cents": 9000}, ASSOCIATE))
    get_success_data(api.fulfill_order(order["id"], ASSOCIATE))

    cust = validate_success(api.get_customer(cid, ANY))
    # base 90, mult 2.0 -> 180; 5000 + 180 = 5180
    assert cust["lifetime_points"] == 5180, f"expected 5180, got {cust['lifetime_points']}"


def test_provisional_points_estimate_not_persisted_at_submit(api):
    """PRD §3.6: "At submit time an implementation may also expose a provisional estimate
    of points that would accrue on the projected total; this estimate is informational
    only and is never persisted to `lifetime_points`."

    Design: Difficulty/dual_variant_calc/loyalty_points_estimate_vs_final_earn
    """
    product = create_active_product(msrp_cents=1000, is_exclusive=False)
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=600)
    customer = create_customer()
    cid = customer["id"]

    order = create_open_order(cid, store["id"])
    add_line(order["id"], cid, product["id"], qty=10, recipient_age_months=60)
    get_success_data(api.submit_order(order["id"], make_customer_headers(cid)))

    cust = validate_success(api.get_customer(cid, ANY))
    assert cust["lifetime_points"] == 0, "submit must not persist points to lifetime_points"


def test_exclusive_product_gets_no_loyalty_discount_for_gold(api):
    """PRD §3.6: "for an exclusive product (`is_exclusive` true) the line discount is 0."

    Design: Corner/calculations/exclusive_product_receives_no_loyalty_discount
    """
    # Promote customer to GOLD using a cheap non-exclusive product.
    warm = create_active_product(msrp_cents=100, is_exclusive=False, category="CRAFT_KIT")
    excl = create_active_product(msrp_cents=5000, is_exclusive=True, category="ACTION_FIGURE")
    store = create_store()
    create_inventory(warm["id"], store["id"], on_hand_qty=6000)
    create_inventory(excl["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    cid = customer["id"]

    wo = create_open_order(cid, store["id"])
    add_line(wo["id"], cid, warm["id"], qty=5000, recipient_age_months=60)
    get_success_data(api.submit_order(wo["id"], make_customer_headers(cid)))
    get_success_data(api.mark_ready_order(wo["id"], ASSOCIATE))
    get_success_data(api.pay_order(wo["id"], {"amount_cents": 500000}, ASSOCIATE))
    get_success_data(api.fulfill_order(wo["id"], ASSOCIATE))

    order = create_open_order(cid, store["id"])
    line = validate_success(
        api.add_order_line(order["id"], {"product_id": excl["id"], "qty": 1, "recipient_age_months": 60},
                           make_customer_headers(cid)),
        expected_status=201,
    )
    assert line["line_discount_cents"] == 0
    assert line["extended_cents"] == 5000


def test_loyalty_tier_becomes_silver_at_1000_points(api):
    """PRD §3.4: "The tier is derived purely from `lifetime_points`: a customer is `GOLD`
    once lifetime points reach at least 5000, `SILVER` once they reach at least 1000 (but
    below 5000), and `BRONZE` otherwise."

    Design: Corner/entities/loyalty_tier_derived_silver_at_threshold
    """
    product = create_active_product(msrp_cents=100, is_exclusive=False)
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=2000)
    customer = create_customer()
    cid = customer["id"]

    order = create_open_order(cid, store["id"])
    add_line(order["id"], cid, product["id"], qty=1000, recipient_age_months=60)
    get_success_data(api.submit_order(order["id"], make_customer_headers(cid)))
    get_success_data(api.mark_ready_order(order["id"], ASSOCIATE))
    get_success_data(api.pay_order(order["id"], {"amount_cents": 100000}, ASSOCIATE))
    get_success_data(api.fulfill_order(order["id"], ASSOCIATE))

    cust = validate_success(api.get_customer(cid, ANY))
    assert cust["lifetime_points"] == 1000
    assert cust["loyalty_tier"] == "SILVER"
