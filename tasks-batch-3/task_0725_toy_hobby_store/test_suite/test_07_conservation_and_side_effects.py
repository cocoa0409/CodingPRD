"""Compensating invariants (inventory, loyalty) and fulfill/convert side effects."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_customer_headers,
    create_active_product, create_store, create_inventory, create_customer,
    create_allocation, create_fulfilled_order, create_requested_return,
    create_open_order, add_line, create_registry, create_approved_special_order,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
ANY = TEST_USERS["any_headers"]


def test_inventory_conserved_across_fulfill_then_full_return(api):
    """PRD §3.13: "Approval also transitions each referenced order line from `ACTIVE` to
    `RETURNED` (each line's parent order must be `FULFILLED`), restocks the returned units
    by adding them to the matching inventory item's `on_hand_qty`, and reverses loyalty
    points as described in §3.8."

    Design: Difficulty/compensating_invariant/inventory_conservation_fulfill_then_return
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    inv = create_inventory(product["id"], store["id"], on_hand_qty=20)
    customer = create_customer()
    order, line = create_fulfilled_order(customer["id"], store["id"], product["id"], qty=5)

    # After fulfill, on_hand is 15.
    ret = create_requested_return(order["id"], line["id"], qty=5)
    validate_success(api.approve_return(ret["id"], {"decision": "APPROVE"}, MANAGER))

    item = validate_success(api.get_inventory(inv["id"], ANY))
    assert item["on_hand_qty"] == 20, "full return should restore on_hand to pre-fulfill value"
    ln = validate_success(api.get_order_line(line["id"], ANY))
    assert ln["status"] == "RETURNED"


def test_fulfill_then_return_restocks_returned_units(api):
    """PRD §3.13: "restocks the returned units by adding them to the matching inventory
    item's `on_hand_qty`"
    PRD §3.7: "For each `ACTIVE` line, the matching inventory item's `on_hand_qty` and
    `reserved_qty` are each reduced by the line's `qty`."

    Design: Difficulty/compensating_invariant/inventory_conservation_fulfill_then_return
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    inv = create_inventory(product["id"], store["id"], on_hand_qty=20)
    customer = create_customer()
    order, line = create_fulfilled_order(customer["id"], store["id"], product["id"], qty=5)

    mid = validate_success(api.get_inventory(inv["id"], ANY))
    assert mid["on_hand_qty"] == 15, "fulfill should decrement on_hand by qty"

    ret = create_requested_return(order["id"], line["id"], qty=5)
    validate_success(api.approve_return(ret["id"], {"decision": "APPROVE"}, MANAGER))
    after = validate_success(api.get_inventory(inv["id"], ANY))
    assert after["on_hand_qty"] == 20


def test_return_reversal_adds_to_points_redeemed(api):
    """PRD §3.8: "The reversal takes the returned gross amount divided by 100, multiplied
    by the tier multiplier that was in effect when the points were originally earned,
    rounded down to whole points, and adds that figure to the customer's `points_redeemed`."

    Design: Difficulty/compensating_invariant/loyalty_points_conservation_fulfill_then_return
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=20)
    customer = create_customer()
    cid = customer["id"]
    order, line = create_fulfilled_order(cid, store["id"], product["id"], qty=5)

    ret = create_requested_return(order["id"], line["id"], qty=5)
    validate_success(api.approve_return(ret["id"], {"decision": "APPROVE"}, MANAGER))

    cust = validate_success(api.get_customer(cid, ANY))
    # gross 5000 / 100 = 50, BRONZE mult 1.0 -> reverse 50 into points_redeemed.
    assert cust["points_redeemed"] == 50


def test_loyalty_points_conserved_across_fulfill_then_full_return(api):
    """PRD §3.8: "The reversal takes the returned gross amount divided by 100, multiplied
    by the tier multiplier that was in effect when the points were originally earned,
    rounded down to whole points, and adds that figure to the customer's `points_redeemed`.
    Because `points_balance` is `lifetime_points` minus `points_redeemed`, a full return of
    a fulfilled order returns the balance to its pre-fulfillment value."

    Design: Difficulty/compensating_invariant/loyalty_points_conservation_fulfill_then_return
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=20)
    customer = create_customer()
    cid = customer["id"]
    # BRONZE, qty 5 @ 1000 => total 5000 => base 50 => earn 50.
    order, line = create_fulfilled_order(cid, store["id"], product["id"], qty=5)

    earned = validate_success(api.get_customer(cid, ANY))
    assert earned["lifetime_points"] == 50

    ret = create_requested_return(order["id"], line["id"], qty=5)
    validate_success(api.approve_return(ret["id"], {"decision": "APPROVE"}, MANAGER))

    cust = validate_success(api.get_customer(cid, ANY))
    assert cust["lifetime_points"] == 50
    assert cust["points_redeemed"] == 50
    assert cust["points_balance"] == 0


def test_convert_commits_allocation(api):
    """PRD §3.10: "Conversion creates an `Order` with a single line, records that order's
    id in `converted_order_id`, moves the special order to `CONVERTED` (terminal), and
    increases the allocation's `committed_qty` by `requested_qty`."

    Design: Corner/consistency_model/convert_commits_allocation
    """
    product = create_active_product(msrp_cents=5000, is_exclusive=True, category="ACTION_FIGURE")
    store = create_store()
    alloc = create_allocation(product["id"], store["id"], allocated_qty=5)
    customer = create_customer()
    so = create_approved_special_order(customer["id"], product["id"], requested_qty=2)

    validate_success(api.convert_special_order(so["id"], ASSOCIATE))

    a = validate_success(api.get_allocation(alloc["id"], ANY))
    assert a["committed_qty"] == 2
    assert a["available_alloc_qty"] == 3
    fetched = validate_success(api.get_special_order(so["id"], ANY))
    assert fetched["status"] == "CONVERTED"


def test_fulfill_bumps_registry_purchased_qty(api):
    """PRD §3.7: "for any fulfilled line whose product matches an open registry item
    belonging to the customer, that item's `purchased_qty` is incremented by the fulfilled
    units."

    Design: Corner/consistency_model/fulfill_bumps_registry_purchased_qty
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    cid = customer["id"]
    registry = create_registry(cid, registry_type="BIRTHDAY")
    item = get_success_data(api.add_registry_item(
        registry["id"], {"product_id": product["id"], "desired_qty": 3},
        make_customer_headers(cid)))

    order = create_open_order(cid, store["id"])
    add_line(order["id"], cid, product["id"], qty=2, recipient_age_months=60)
    get_success_data(api.submit_order(order["id"], make_customer_headers(cid)))
    get_success_data(api.mark_ready_order(order["id"], ASSOCIATE))
    get_success_data(api.pay_order(order["id"], {"amount_cents": 2000}, ASSOCIATE))
    validate_success(api.fulfill_order(order["id"], ASSOCIATE))

    fetched = validate_success(api.get_registry_item(item["id"], ANY))
    assert fetched["purchased_qty"] == 2
