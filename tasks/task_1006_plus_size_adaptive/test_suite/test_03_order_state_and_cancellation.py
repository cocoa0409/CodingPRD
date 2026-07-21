"""Order state guards, cancellation reversals, and suspended-account gating.

Queue A (Difficulty): order_cancel_restores_inventory_reserved,
order_cancel_restores_loyalty_points_balance, checkout_blocked_by_suspended_customer.
Queue B (Corner): capture-before-authorize, pick-before-capture, cancel-after-shipped.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_customer_headers,
    register_customer, seed_loyalty, suspend_customer,
    open_order, add_line, checkout, order_transition,
    setup_order_with_line,
)

SM = TEST_USERS["store_manager_headers"]


# ---------------------------------------------------------------------------
# order_cancel_restores_inventory_reserved (Queue A)
# ---------------------------------------------------------------------------
def test_cancel_releases_reserved_inventory(api):
    """PRD §3.3: "For each line, the variant's `inventory_reserved` is reduced by the
    line's `quantity`, releasing the reservation while leaving `inventory_on_hand`
    unchanged."

    Design: Difficulty/compensating_invariant/order_cancel_restores_inventory_reserved
    """
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10}, quantity=3)
    order_transition(api, ctx["order"]["id"], "CANCEL", customer_id=ctx["customer"]["id"])
    variant = validate_success(api.get_variant(ctx["variant"]["id"], SM))
    assert variant["inventory_reserved"] == 0


def test_cancel_leaves_on_hand_unchanged(api):
    """PRD §3.3: "For each line, the variant's `inventory_reserved` is reduced by the
    line's `quantity`, releasing the reservation while leaving `inventory_on_hand`
    unchanged."

    Design: Difficulty/compensating_invariant/order_cancel_restores_inventory_reserved
    """
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10}, quantity=3)
    order_transition(api, ctx["order"]["id"], "CANCEL", customer_id=ctx["customer"]["id"])
    variant = validate_success(api.get_variant(ctx["variant"]["id"], SM))
    assert variant["inventory_on_hand"] == 10
    assert variant["inventory_available"] == 10


# ---------------------------------------------------------------------------
# order_cancel_restores_loyalty_points_balance (Queue A)
# ---------------------------------------------------------------------------
def test_cancel_restores_redeemed_points_to_balance(api):
    """PRD §3.3: "The customer's `loyalty_points_balance` is increased by
    `loyalty_redeemed_points`, reversing any redemption, and their
    `wallet_credit_cents` is increased by `wallet_applied_cents`, reversing any
    wallet spend."

    Design: Difficulty/compensating_invariant/order_cancel_restores_loyalty_points_balance
    """
    customer = register_customer(api)
    seed_loyalty(api, customer["id"], 200)
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10})
    order = open_order(api, customer["id"])
    add_line(api, order["id"], customer["id"], ctx["variant"]["id"], 1)
    checkout(api, order["id"], customer["id"], loyalty_redeem_points=100)
    order_transition(api, order["id"], "CANCEL", customer_id=customer["id"])
    result = validate_success(api.get_customer(customer["id"], SM))
    assert result["loyalty_points_balance"] == 200


def test_cancel_leaves_lifetime_points_untouched(api):
    """PRD §3.1: "`loyalty_lifetime_points` is the cumulative total ever earned; it
    drives the customer's tier and is never decremented by redemption."

    Design: Difficulty/compensating_invariant/order_cancel_restores_loyalty_points_balance
    """
    customer = register_customer(api)
    seed_loyalty(api, customer["id"], 200)
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10})
    order = open_order(api, customer["id"])
    add_line(api, order["id"], customer["id"], ctx["variant"]["id"], 1)
    checkout(api, order["id"], customer["id"], loyalty_redeem_points=100)
    order_transition(api, order["id"], "CANCEL", customer_id=customer["id"])
    result = validate_success(api.get_customer(customer["id"], SM))
    assert result["loyalty_lifetime_points"] == 200


# ---------------------------------------------------------------------------
# checkout_blocked_by_suspended_customer (Queue A)
# ---------------------------------------------------------------------------
def test_checkout_rejected_when_customer_suspended(api):
    """PRD §3.3: "the owning customer's `account_status` must be `ACTIVE`, else
    `ERR_CUSTOMER_SUSPENDED`".

    Design: Difficulty/cross_entity_state_dependency/checkout_blocked_by_suspended_customer
    """
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10})
    suspend_customer(api, ctx["customer"]["id"])
    resp = api.checkout_order(ctx["order"]["id"], {}, make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED.value)


def test_checkout_blocked_by_suspension_leaves_payment_pending(api):
    """PRD §3.1: "Account status gates checkout: a customer whose account is not
    `ACTIVE` cannot authorize an order."

    Design: Difficulty/cross_entity_state_dependency/checkout_blocked_by_suspended_customer
    """
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10})
    suspend_customer(api, ctx["customer"]["id"])
    api.checkout_order(ctx["order"]["id"], {}, make_customer_headers(ctx["customer"]["id"]))
    order = validate_success(api.get_order(ctx["order"]["id"], SM))
    assert order["payment_status"] == "PENDING"


# ---------------------------------------------------------------------------
# Corner: invalid state transitions
# ---------------------------------------------------------------------------
def test_capture_before_authorize_returns_invalid_state(api):
    """PRD §3.3: "Capturing payment moves `payment_status` from `AUTHORIZED` to
    `CAPTURED` and requires that payment currently be `AUTHORIZED`."
    PRD §3.3: "Any order transition requested from a state that does not permit it is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/order_capture_before_authorize_returns_invalid_state
    """
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10})
    resp = api.transition_order(ctx["order"]["id"], {"action": "CAPTURE"}, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    order = validate_success(api.get_order(ctx["order"]["id"], SM))
    assert order["payment_status"] == "PENDING"


def test_pick_before_capture_returns_invalid_state(api):
    """PRD §3.3: "starting to pick moves `fulfillment_status` from `UNFULFILLED` to
    `PICKING` and is permitted only when `payment_status` is `CAPTURED`, the single
    cross-dimension gate of the model."

    Design: Corner/state_machines/order_pick_before_capture_returns_invalid_state
    """
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10})
    checkout(api, ctx["order"]["id"], ctx["customer"]["id"])
    resp = api.transition_order(ctx["order"]["id"], {"action": "PICK"}, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    order = validate_success(api.get_order(ctx["order"]["id"], SM))
    assert order["fulfillment_status"] == "UNFULFILLED"


def test_cancel_after_shipped_returns_invalid_state(api):
    """PRD §3.3: "Cancelling an order is available to the customer or a store manager
    while `fulfillment_status` is either `UNFULFILLED` or `PICKING`".

    Design: Corner/state_machines/order_cancel_after_shipped_returns_invalid_state
    """
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10})
    checkout(api, ctx["order"]["id"], ctx["customer"]["id"])
    order_transition(api, ctx["order"]["id"], "CAPTURE")
    order_transition(api, ctx["order"]["id"], "PICK")
    order_transition(api, ctx["order"]["id"], "SHIP")
    resp = api.transition_order(
        ctx["order"]["id"], {"action": "CANCEL"}, make_customer_headers(ctx["customer"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    order = validate_success(api.get_order(ctx["order"]["id"], SM))
    assert order["fulfillment_status"] == "SHIPPED"
