"""Order placement/fulfillment lifecycle, parallel status dimensions, placement
preconditions, and the state-over-fiscal validation ordering."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_customer, make_product, make_variant, make_order, add_line,
    setup_cart_order, setup_placed_order, suspend_customer,
    TEST_USERS,
)
from test_helpers.test_users import make_customer_headers

FULFILL = TEST_USERS["fulfillment_headers"]


# ─── Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions ───
def test_place_advances_fulfillment_and_payment_dimensions(api):
    """PRD §2.9: "Placing an order advances fulfillment to `PLACED` while
    independently advancing payment to `PAID`; later events move each dimension on
    its own schedule as described in Section 3."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    ctx = setup_cart_order(12000, quantity=1, on_hand_qty=5)
    resp = api.place_order(ctx["order_id"], {"redeem_points": 0}, ctx["cust_headers"])
    data = validate_success(resp, 200)
    assert data["fulfillment_status"] == "PLACED"
    assert data["payment_status"] == "PAID"


def test_fulfill_advances_fulfillment_while_payment_stays_paid(api):
    """PRD §3.3: "Fulfilling a placed order — a `FulfillmentOps` or `PlatformAdmin`
    action — advances `fulfillment_status` from `PLACED` to `FULFILLED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    ctx = setup_placed_order(12000, quantity=1, on_hand_qty=5)
    resp = api.fulfill_order(ctx["order_id"], FULFILL)
    data = validate_success(resp, 200)
    assert data["fulfillment_status"] == "FULFILLED"
    assert data["payment_status"] == "PAID"


# ─── Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_double_place ───
def test_double_place_returns_invalid_state(api):
    """PRD §2.8: "the tiers themselves are the binding order — for instance, a
    request that both targets a wrong state and would exhaust allocation surfaces
    the state error first."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_double_place
    """
    ctx = setup_placed_order(9000, quantity=1, on_hand_qty=5)
    resp = api.place_order(ctx["order_id"], {"redeem_points": 999}, ctx["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_state_check_preempts_insufficient_points(api):
    """PRD §2.8: "(4) the target resource being in a valid state for the requested
    transition (`ERR_INVALID_STATE`, HTTP 409)".
    PRD §2.8: "(9) fiscal checks — insufficient loyalty points
    (`ERR_INSUFFICIENT_POINTS`)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_double_place
    """
    ctx = setup_placed_order(9000, quantity=1, on_hand_qty=5)
    resp = api.place_order(ctx["order_id"], {"redeem_points": 999}, ctx["cust_headers"])
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_INVALID_STATE"
    assert body["data"]["error_id"] != "ERR_INSUFFICIENT_POINTS"
    assert resp.status_code == 409


# ─── Difficulty/boundary_precision_check/place_empty_order_zero_lines_boundary ───
def test_place_empty_cart_rejected_empty_order(api):
    """PRD §3.2: "It must contain at least one `ACTIVE` line, or the placement is
    rejected with `ERR_EMPTY_ORDER`."

    Design: Difficulty/boundary_precision_check/place_empty_order_zero_lines_boundary
    """
    cust = make_customer()
    order = make_order(cust["id"])
    resp = api.place_order(order["id"], {"redeem_points": 0}, make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER, 422)


def test_place_with_one_active_line_succeeds(api):
    """PRD §3.2: "It must contain at least one `ACTIVE` line, or the placement is
    rejected with `ERR_EMPTY_ORDER`." — a cart holding one active line clears the
    boundary and places.

    Design: Difficulty/boundary_precision_check/place_empty_order_zero_lines_boundary
    """
    ctx = setup_cart_order(9000, quantity=1, on_hand_qty=5)
    resp = api.place_order(ctx["order_id"], {"redeem_points": 0}, ctx["cust_headers"])
    data = validate_success(resp, 200)
    assert data["fulfillment_status"] == "PLACED"


# ─── Difficulty/cross_entity_state_dependency/place_requires_customer_active ───
def test_suspended_customer_cannot_place_order(api):
    """PRD §3.2: "The owning customer's account `status` must be `ACTIVE`; a
    suspended account is rejected with `ERR_CUSTOMER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/place_requires_customer_active
    """
    ctx = setup_cart_order(9000, quantity=1, on_hand_qty=5, concentration="EDT")
    suspend_customer(ctx["cust_id"])
    resp = api.place_order(ctx["order_id"], {"redeem_points": 0}, ctx["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED, 403)


def test_rejected_place_leaves_order_in_cart(api):
    """PRD §3.8: "A suspended customer is barred from placing orders and from
    claiming allocation, as enforced by `ERR_CUSTOMER_SUSPENDED` in those
    workflows." — the blocked placement does not advance the cart.

    Design: Difficulty/cross_entity_state_dependency/place_requires_customer_active
    """
    ctx = setup_cart_order(9000, quantity=1, on_hand_qty=5, concentration="EDT")
    suspend_customer(ctx["cust_id"])
    api.place_order(ctx["order_id"], {"redeem_points": 0}, ctx["cust_headers"])
    order = validate_success(api.get_order(ctx["order_id"], ctx["cust_headers"]), 200)
    assert order["fulfillment_status"] == "CART"


# ─── Corner instances ─────────────────────────────────
def test_fulfill_cart_order_rejected(api):
    """PRD §3.3: "Fulfilling a placed order — a `FulfillmentOps` or `PlatformAdmin`
    action — advances `fulfillment_status` from `PLACED` to `FULFILLED` and
    requires only that the order currently be `PLACED`." — a CART order cannot be
    fulfilled.

    Design: Corner/state_machines/fulfill_cart_order_returns_409
    """
    ctx = setup_cart_order(9000, quantity=1, on_hand_qty=5, concentration="EDT")
    resp = api.fulfill_order(ctx["order_id"], FULFILL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_insufficient_stock_on_place(api):
    """PRD §3.2: "the variant's `on_hand_qty` must be at least the line's quantity
    — availability exactly equal to the quantity is acceptable, one unit short is
    rejected with `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/validations/insufficient_stock_on_place_returns_409
    """
    cust = make_customer()
    prod = make_product(concentration="EDT")
    var = make_variant(prod["id"], kind="DECANT", volume_ml=10, unit_price_cents=3500, on_hand_qty=2)
    order = make_order(cust["id"])
    add_line(order["id"], cust["id"], var["id"], 3)
    resp = api.place_order(order["id"], {"redeem_points": 0}, make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK, 409)


def test_insufficient_points_redeem_rejected(api):
    """PRD §3.2: "the optional `redeem_points` amount supplied at placement must
    not exceed the customer's current `loyalty_points_balance`, or the request is
    rejected with `ERR_INSUFFICIENT_POINTS`."

    Design: Corner/validations/insufficient_points_redeem_returns_422
    """
    cust = make_customer()
    prod = make_product(concentration="EDT")
    var = make_variant(prod["id"], kind="DECANT", volume_ml=10, unit_price_cents=3500, on_hand_qty=5)
    order = make_order(cust["id"])
    add_line(order["id"], cust["id"], var["id"], 1)
    resp = api.place_order(order["id"], {"redeem_points": 5}, make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS, 422)
