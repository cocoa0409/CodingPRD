"""Order assembly, the pinned order-total evaluation, loyalty points, and tier boundaries.

Queue A: combinatorial_formula/order_total_pinned_eval_order,
         non_linear_state_machine/order_parallel_payment_fulfillment_dimensions,
         boundary_precision_check/loyalty_tier_gold_inclusive_boundary.
Queue B: order line side-effect, initial states, loyalty points, immediate consistency.
"""
from test_helpers import (
    validate_success,
    TEST_USERS, make_customer_headers,
    register_customer, create_product, create_inventory_item, open_order, add_line,
    set_loyalty_points, assert_order_totals_consistent,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["store_clerk_headers"]


# ---------------------------------------------------------------------------
# Queue A — order_total_pinned_eval_order (>=2 tests)
# ---------------------------------------------------------------------------
def _silver_order_two_new_nm(api):
    buyer = register_customer(api, full_name="Silver Buyer")
    set_loyalty_points(api, customer_id=buyer["id"], delta_points=150)
    product = create_product(api, artist="Radiohead", title="OK Computer", format="VINYL",
                             base_price_cents=2000)
    it1 = create_inventory_item(api, product_id=product["id"], is_used=False, condition_grade="NM")
    it2 = create_inventory_item(api, product_id=product["id"], is_used=False, condition_grade="NM")
    order = open_order(api, customer=buyer, channel="ONLINE")
    add_line(api, order=order, customer=buyer, item=it1)
    hdr = make_customer_headers(buyer["id"])
    resp = api.add_order_line(order["id"], {"inventory_item_id": it2["id"]}, hdr)
    return validate_success(resp, expected_status=201), order, buyer


def test_order_total_subtotal_and_discount_pinned_order(api):
    """PRD §3.2: "First, subtotal_cents is the sum over all lines of each line's
    unit_price_cents multiplied by its qty." "Third, discount_cents is that new-item
    subtotal multiplied by the loyalty discount rate for the buyer's current loyalty_tier
    — 0 percent for STANDARD, 5 percent for SILVER, and 10 percent for GOLD — with the
    single product rounded half up to whole cents".

    Design: Difficulty/combinatorial_formula/order_total_pinned_eval_order
    """
    _line, order, buyer = _silver_order_two_new_nm(api)
    data = validate_success(api.get_order(order["id"], make_customer_headers(buyer["id"])))
    assert data["subtotal_cents"] == 4000, f"expected 4000, got {data['subtotal_cents']}"
    assert data["discount_cents"] == 200, f"SILVER 5% of 4000 must be 200, got {data['discount_cents']}"


def test_order_total_shipping_on_subtotal_and_grand_total(api):
    """PRD §3.2: "Fourth, shipping_cents is zero when the channel is IN_STORE; for an
    ONLINE order it is zero when subtotal_cents is at least 5000 cents and otherwise a
    flat 599 cents. Fifth, total_cents is subtotal_cents minus discount_cents plus
    shipping_cents."

    Design: Difficulty/combinatorial_formula/order_total_pinned_eval_order
    """
    _line, order, buyer = _silver_order_two_new_nm(api)
    data = validate_success(api.get_order(order["id"], make_customer_headers(buyer["id"])))
    assert data["shipping_cents"] == 599, f"ONLINE subtotal 4000<5000 must ship 599, got {data['shipping_cents']}"
    assert data["total_cents"] == 4399, f"4000-200+599 must be 4399, got {data['total_cents']}"
    assert_order_totals_consistent(data)


# ---------------------------------------------------------------------------
# Queue A — order_parallel_payment_fulfillment_dimensions (>=2 tests)
# ---------------------------------------------------------------------------
def _online_order_reserved_line(api):
    buyer = register_customer(api, full_name="Parallel")
    product = create_product(api, artist="Pink Floyd", title="Wish You Were Here",
                             format="VINYL", base_price_cents=3000)
    item = create_inventory_item(api, product_id=product["id"], is_used=False, condition_grade="NM")
    order = open_order(api, customer=buyer, channel="ONLINE")
    add_line(api, order=order, customer=buyer, item=item)
    return buyer, order


def test_authorize_payment_advances_only_payment_dimension(api):
    """PRD §3.3: "A Customer authorizes payment on their own order, moving payment_status
    from UNPAID to AUTHORIZED; this is permitted only when the order has at least one
    OrderLine and its fulfillment_status is still PENDING."
    PRD §3.2: "these two dimensions advance independently, which is why the order carries
    them as separate fields."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
    """
    buyer, order = _online_order_reserved_line(api)
    resp = api.authorize_payment(order["id"], make_customer_headers(buyer["id"]))
    data = validate_success(resp)
    assert data["payment_status"] == "AUTHORIZED", f"got {data['payment_status']}"
    assert data["fulfillment_status"] == "RESERVED", f"got {data['fulfillment_status']}"


def test_fulfillment_reserved_before_any_payment(api):
    """PRD §3.2: "Adding the first line advances the order's fulfillment_status from
    PENDING to RESERVED." PRD §3.2: "A fresh order starts with payment_status of UNPAID
    and fulfillment_status of PENDING; these two dimensions advance independently".

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
    """
    buyer, order = _online_order_reserved_line(api)
    data = validate_success(api.get_order(order["id"], make_customer_headers(buyer["id"])))
    assert data["fulfillment_status"] == "RESERVED", f"got {data['fulfillment_status']}"
    assert data["payment_status"] == "UNPAID", f"payment must still be UNPAID, got {data['payment_status']}"


# ---------------------------------------------------------------------------
# Queue A — loyalty_tier_gold_inclusive_boundary (X-1, X, X+1)
# ---------------------------------------------------------------------------
def test_loyalty_tier_gold_at_exactly_500(api):
    """PRD §3.3: "a customer with at least 500 points is GOLD ... These boundaries are
    inclusive at the stated lower bound."

    Design: Difficulty/boundary_precision_check/loyalty_tier_gold_inclusive_boundary
    """
    customer = register_customer(api, full_name="Gold Edge")
    data = set_loyalty_points(api, customer_id=customer["id"], delta_points=500)
    assert data["loyalty_points"] == 500, f"got {data['loyalty_points']}"
    assert data["loyalty_tier"] == "GOLD", f"500 points must be GOLD, got {data['loyalty_tier']}"


def test_loyalty_tier_silver_just_below_gold(api):
    """PRD §3.3: "a customer with at least 100 (but fewer than 500) points is SILVER ...
    These boundaries are inclusive at the stated lower bound."

    Design: Difficulty/boundary_precision_check/loyalty_tier_gold_inclusive_boundary
    """
    customer = register_customer(api, full_name="Silver Edge")
    data = set_loyalty_points(api, customer_id=customer["id"], delta_points=499)
    assert data["loyalty_points"] == 499, f"got {data['loyalty_points']}"
    assert data["loyalty_tier"] == "SILVER", f"499 points must be SILVER, got {data['loyalty_tier']}"


def test_loyalty_tier_gold_just_above_boundary(api):
    """PRD §3.3: "a customer with at least 500 points is GOLD ... These boundaries are
    inclusive at the stated lower bound."

    Design: Difficulty/boundary_precision_check/loyalty_tier_gold_inclusive_boundary
    """
    customer = register_customer(api, full_name="Gold Plus")
    data = set_loyalty_points(api, customer_id=customer["id"], delta_points=501)
    assert data["loyalty_tier"] == "GOLD", f"501 points must be GOLD, got {data['loyalty_tier']}"


# ---------------------------------------------------------------------------
# Queue B — endpoints / entities / calculations / consistency
# ---------------------------------------------------------------------------
def test_add_order_line_reserves_item_and_snapshots_price(api):
    """PRD §3.2: "Every copy added this way must currently be in AVAILABLE or ON_DISPLAY
    status, and adding it moves that copy to RESERVED so no other buyer can claim it. The
    line captures a unit_price_cents snapshot of the copy's list_price_cents at the moment
    the line is created". PRD §3.2: "Adding the first line advances the order's
    fulfillment_status from PENDING to RESERVED."

    Design: Corner/endpoints/add_order_line_reserves_item_side_effect
    """
    buyer = register_customer(api, full_name="Liner")
    product = create_product(api, artist="Blur", title="Parklife", format="VINYL",
                             base_price_cents=3000)
    item = create_inventory_item(api, product_id=product["id"], is_used=False, condition_grade="NM")
    order = open_order(api, customer=buyer, channel="ONLINE")
    hdr = make_customer_headers(buyer["id"])
    resp = api.add_order_line(order["id"], {"inventory_item_id": item["id"]}, hdr)
    line = validate_success(resp, expected_status=201)
    assert line["unit_price_cents"] == 3000, f"snapshot must be 3000, got {line['unit_price_cents']}"
    item_after = validate_success(api.get_inventory_item(item["id"], hdr))
    assert item_after["status"] == "RESERVED", f"item must be RESERVED, got {item_after['status']}"
    order_after = validate_success(api.get_order(order["id"], hdr))
    assert order_after["fulfillment_status"] == "RESERVED", f"got {order_after['fulfillment_status']}"


def test_newly_created_order_starts_in_initial_states(api):
    """PRD §3.2: "A fresh order starts with payment_status of UNPAID and fulfillment_status
    of PENDING; these two dimensions advance independently".

    Design: Corner/state_machines/newly_created_order_starts_in_initial_states
    """
    buyer = register_customer(api, full_name="Init")
    resp = api.create_order({"customer_id": buyer["id"], "channel": "ONLINE"},
                            make_customer_headers(buyer["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["payment_status"] == "UNPAID", f"got {data['payment_status']}"
    assert data["fulfillment_status"] == "PENDING", f"got {data['fulfillment_status']}"


def test_loyalty_points_gold_multiplier_awarded_at_capture(api):
    """PRD §3.3: "The base award is one point for each whole dollar of total_cents — that
    is, total_cents divided by 100 and floored to a whole number. That base is then
    multiplied by the tier multiplier for the buyer's loyalty_tier — 1.0 for STANDARD,
    1.0 for SILVER, and 1.5 for GOLD — and the product is floored to a whole number of points."

    Design: Corner/calculations/loyalty_points_gold_multiplier
    """
    buyer = register_customer(api, full_name="Gold Points")
    set_loyalty_points(api, customer_id=buyer["id"], delta_points=500)
    product = create_product(api, artist="Yes", title="Fragile", format="VINYL",
                             base_price_cents=2000)
    hdr = make_customer_headers(buyer["id"])
    order = open_order(api, customer=buyer, channel="IN_STORE")
    for _ in range(3):
        it = create_inventory_item(api, product_id=product["id"], is_used=False, condition_grade="NM")
        add_line(api, order=order, customer=buyer, item=it)
    validate_success(api.authorize_payment(order["id"], hdr))
    captured = validate_success(api.capture_payment(order["id"], {}, CLERK))
    assert captured["total_cents"] == 5400, f"6000 - 600 (GOLD 10%) must be 5400, got {captured['total_cents']}"
    assert captured["points_earned"] == 81, f"floor(54 * 1.5) must be 81, got {captured['points_earned']}"
    cust = validate_success(api.get_customer(buyer["id"], hdr))
    assert cust["loyalty_points"] == 581, f"500 + 81 must be 581, got {cust['loyalty_points']}"


def test_order_totals_visible_immediately_on_line_add(api):
    """PRD §2.7: "every such cascade resolves atomically within the request that triggers
    it — there is no deferred or eventual settlement."
    PRD §3.2: "Order totals are recomputed on every line addition".

    Design: Corner/consistency_model/order_totals_visible_immediately_on_line_add
    """
    buyer = register_customer(api, full_name="Immediate")
    product = create_product(api, artist="Air", title="Moon Safari", format="VINYL",
                             base_price_cents=2000)
    item = create_inventory_item(api, product_id=product["id"], is_used=True, condition_grade="VG")
    order = open_order(api, customer=buyer, channel="IN_STORE")
    hdr = make_customer_headers(buyer["id"])
    add_line(api, order=order, customer=buyer, item=item)
    data = validate_success(api.get_order(order["id"], hdr))
    assert data["subtotal_cents"] == 1200, f"used VG base-2000 must be 1200, got {data['subtotal_cents']}"
    assert data["shipping_cents"] == 0, f"IN_STORE must ship 0, got {data['shipping_cents']}"
    assert data["total_cents"] == 1200, f"got {data['total_cents']}"
