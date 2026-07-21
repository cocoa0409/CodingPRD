"""Order cart, inventory reservation, checkout totals, and delivery loyalty.

Queue A (Difficulty): order_total_nonlinear_min_stack,
add_line_inventory_zero_boundary_rejected, order_parallel_payment_fulfillment_dimensions.
Queue B (Corner): empty-order guard, FK not-found on add-line, deliver awards loyalty.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_customer_headers,
    register_customer, seed_loyalty, adjust_wallet,
    create_product, create_variant,
    open_order, add_line, checkout, order_transition,
    setup_order_with_line, setup_delivered_order,
    MISSING_UUID,
)

SM = TEST_USERS["store_manager_headers"]


# ---------------------------------------------------------------------------
# order_total_nonlinear_min_stack (Queue A)
# ---------------------------------------------------------------------------
def _vip_order_ready_for_stacked_checkout(api):
    """VIP customer (2000 pts), 500 wallet, 2 units @ 6800 (subtotal 13600)."""
    customer = register_customer(api)
    seed_loyalty(api, customer["id"], 2000)
    adjust_wallet(api, customer["id"], 500)
    product = create_product(api, base_price_cents=6000)
    variant = create_variant(api, product["id"], size_code=22, price_delta_cents=800,
                             inventory_on_hand=10)
    order = open_order(api, customer["id"])
    add_line(api, order["id"], customer["id"], variant["id"], 2)
    return customer, order


def test_order_total_stacks_tier_discount_and_wallet(api):
    """PRD §3.3: "`subtotal_cents` is the sum of `line_total_cents` across all of the
    order's lines."
    PRD §3.3: "`tier_discount_cents` is `subtotal_cents` multiplied by that rate,
    rounded half up to whole cents."
    PRD §3.3: "`total_cents`, the amount authorized, is the post-redemption amount
    minus `wallet_applied_cents`."

    Design: Difficulty/combinatorial_formula/order_total_nonlinear_min_stack
    """
    customer, order = _vip_order_ready_for_stacked_checkout(api)
    resp = api.checkout_order(
        order["id"], {"loyalty_redeem_points": 100, "use_wallet_credit": True},
        make_customer_headers(customer["id"]),
    )
    data = validate_success(resp, expected_status=200)
    assert data["subtotal_cents"] == 13600
    assert data["tier_discount_cents"] == 1360
    assert data["total_cents"] == 11240


def test_order_total_redeem_and_wallet_are_min_capped(api):
    """PRD §3.3: "`loyalty_redeemed_cents` is the least of three quantities: the
    redeemed points valued at 5 cents per point, the redemption cap from the previous
    step, and the tier-adjusted amount from step 3."
    PRD §3.3: "`wallet_applied_cents` is applied only when `use_wallet_credit` is
    true, in which case it is the lesser of the customer's `wallet_credit_cents` and
    the post-redemption amount; otherwise it is 0."

    Design: Difficulty/combinatorial_formula/order_total_nonlinear_min_stack
    """
    customer, order = _vip_order_ready_for_stacked_checkout(api)
    resp = api.checkout_order(
        order["id"], {"loyalty_redeem_points": 100, "use_wallet_credit": True},
        make_customer_headers(customer["id"]),
    )
    data = validate_success(resp, expected_status=200)
    assert data["loyalty_redeemed_cents"] == 500
    assert data["wallet_applied_cents"] == 500


# ---------------------------------------------------------------------------
# add_line_inventory_zero_boundary_rejected (Queue A)
# ---------------------------------------------------------------------------
def test_add_line_at_zero_availability_is_rejected(api):
    """PRD §3.3: "Adding the line also reserves stock — the variant's
    `inventory_reserved` rises by `quantity` — which requires that the variant's
    `inventory_available` be at least `quantity`; when it is not, the line is refused
    with `ERR_INSUFFICIENT_INVENTORY`."

    Design: Difficulty/boundary_precision_check/add_line_inventory_zero_boundary_rejected
    """
    ctx = setup_order_with_line(
        api, variant_overrides={"size_code": 22, "inventory_on_hand": 2}, quantity=2
    )
    resp = api.add_order_line(
        ctx["order"]["id"], {"variant_id": ctx["variant"]["id"], "quantity": 1},
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)
    variant = validate_success(api.get_variant(ctx["variant"]["id"], SM))
    assert variant["inventory_reserved"] == 2
    assert variant["inventory_available"] == 0


def test_add_line_at_exactly_available_quantity_succeeds(api):
    """PRD §3.3: "Adding the line also reserves stock — the variant's
    `inventory_reserved` rises by `quantity` — which requires that the variant's
    `inventory_available` be at least `quantity`; when it is not, the line is refused
    with `ERR_INSUFFICIENT_INVENTORY`."

    Design: Difficulty/boundary_precision_check/add_line_inventory_zero_boundary_rejected
    """
    ctx = setup_order_with_line(
        api, variant_overrides={"size_code": 22, "inventory_on_hand": 3}, quantity=2
    )
    # inventory_available is now 1; a further line of exactly 1 is at the >= boundary.
    resp = api.add_order_line(
        ctx["order"]["id"], {"variant_id": ctx["variant"]["id"], "quantity": 1},
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_success(resp, expected_status=201)
    variant = validate_success(api.get_variant(ctx["variant"]["id"], SM))
    assert variant["inventory_reserved"] == 3
    assert variant["inventory_available"] == 0


# ---------------------------------------------------------------------------
# order_parallel_payment_fulfillment_dimensions (Queue A)
# ---------------------------------------------------------------------------
def test_capture_advances_payment_while_fulfillment_stays_unfulfilled(api):
    """PRD §2.8: "An `Order` advances along two independent status tracks that evolve
    on separate timelines."
    PRD §3.3: "Capturing payment moves `payment_status` from `AUTHORIZED` to
    `CAPTURED` and requires that payment currently be `AUTHORIZED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
    """
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10})
    checkout(api, ctx["order"]["id"], ctx["customer"]["id"])
    order = order_transition(api, ctx["order"]["id"], "CAPTURE")
    assert order["payment_status"] == "CAPTURED"
    assert order["fulfillment_status"] == "UNFULFILLED"


def test_pick_advances_fulfillment_independently_after_capture(api):
    """PRD §3.3: "starting to pick moves `fulfillment_status` from `UNFULFILLED` to
    `PICKING` and is permitted only when `payment_status` is `CAPTURED`, the single
    cross-dimension gate of the model."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
    """
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10})
    checkout(api, ctx["order"]["id"], ctx["customer"]["id"])
    order_transition(api, ctx["order"]["id"], "CAPTURE")
    order = order_transition(api, ctx["order"]["id"], "PICK")
    assert order["payment_status"] == "CAPTURED"
    assert order["fulfillment_status"] == "PICKING"


# ---------------------------------------------------------------------------
# Corner instances
# ---------------------------------------------------------------------------
def test_checkout_empty_order_returns_empty_order(api):
    """PRD §3.3: "the order must hold at least one line, else `ERR_EMPTY_ORDER`".

    Design: Corner/validations/checkout_empty_order_returns_empty_order
    """
    customer = register_customer(api)
    order = open_order(api, customer["id"])
    resp = api.checkout_order(order["id"], {}, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value)


def test_add_line_with_nonexistent_variant_returns_not_found(api):
    """PRD §2.10: "Foreign keys supplied in a request body — `product_id`,
    `variant_id`, `order_id`, `specialist_id`, `subscription_id`,
    `exchange_variant_id`, and each id in `line_ids` — are validated for existence
    under the same principle and likewise yield `ERR_NOT_FOUND` when unresolved."

    Design: Corner/endpoints/add_line_nonexistent_variant_returns_not_found
    """
    customer = register_customer(api)
    order = open_order(api, customer["id"])
    resp = api.add_order_line(
        order["id"], {"variant_id": MISSING_UUID, "quantity": 1},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_deliver_awards_floor_loyalty_points_without_tier_change(api):
    """PRD §3.3: "sets the order's `points_earned` to `total_cents` divided by 100
    and rounded down to a whole number (one point per whole dollar authorized)."
    PRD §3.3: "both `loyalty_points_balance` and `loyalty_lifetime_points` increase
    by `points_earned`".

    Design: Corner/endpoints/order_deliver_awards_loyalty_points
    """
    ctx = setup_delivered_order(api, variant_overrides={"inventory_on_hand": 10})
    order = ctx["order"]
    assert order["points_earned"] == 60
    customer = validate_success(api.get_customer(ctx["customer"]["id"], SM))
    assert customer["loyalty_points_balance"] == 60
    assert customer["loyalty_lifetime_points"] == 60
    assert customer["loyalty_tier"] == "STANDARD"
