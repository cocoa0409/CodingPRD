"""Validation precedence and numeric boundary precision.

Difficulty queue: priority_pair_validation_conflict, boundary_precision_check.

Note: the difficulty instance
priority_pair_validation_conflict/license_safety_before_inventory_on_place_double_fail
is intentionally NOT translated. It asserts ERR_LICENSE_REQUIRED pre-empts
ERR_INSUFFICIENT_INVENTORY, but PRD §2.10 says the relative ordering of two §3
business rules on one endpoint is stated alongside the workflow that owns them, and
§3.3 does not pin license-before-inventory (it lists the inventory check first).
A faithful PRD-only implementer could return either error, so the precedence is
not uniquely derivable (error-precedence Silence pattern).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    create_store,
    create_sku,
    create_customer,
    stock_sku,
    create_inventory_row,
    setup_placed_order,
    create_draft_order,
    add_order_line,
    place_order,
    make_customer_headers,
    get_inventory,
    get_customer,
    setup_ready_order,
    fulfill_order,
)


# ===========================================================================
# priority_pair_validation_conflict / state_before_inventory_on_place_double_fail
# ===========================================================================
def test_replace_reserved_order_returns_invalid_state_not_inventory(api):
    """PRD §2.10: "Next, for transition endpoints, that the target resource is in a
    state from which the requested transition is defined (`ERR_INVALID_STATE`).
    Only after all of these do the business-specific rules described in §3 apply."
    PRD §3.3: "If the order has no lines or the payment axis is not `UNPAID`, the
    placement is an undefined transition and is rejected with `ERR_INVALID_STATE`."

    A SKU stocked with only 1 unit; an order with one line qty 1 is placed (now
    RESERVED, consuming the unit). Re-placing the RESERVED order would fail both the
    state check (not DRAFT) and the inventory check (0 available); the state error
    wins because state precedes all §3 business rules.

    Design: Difficulty/priority_pair_validation_conflict/state_before_inventory_on_place_double_fail
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Ball", base_price_cents=2000, size_label="NA")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 1)

    placed, _ = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    assert placed["fulfillment_status"] == "RESERVED"

    res = api.place_order(placed["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_place_already_reserved_order_does_not_double_reserve(api):
    """PRD §3.3: "If the order has no lines or the payment axis is not `UNPAID`, the
    placement is an undefined transition and is rejected with `ERR_INVALID_STATE`."

    The rejected re-place leaves the stock row untouched (reserved_qty stays 1),
    confirming the undefined transition does not run the reserve side effect.

    Design: Difficulty/priority_pair_validation_conflict/state_before_inventory_on_place_double_fail
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Ball", base_price_cents=2000, size_label="NA")
    customer = create_customer(home_state_code="CA")
    inv = stock_sku(store["id"], sku["id"], 1)

    placed, _ = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    res = api.place_order(placed["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    inv_after = get_inventory(inv["id"])
    assert inv_after["reserved_qty"] == 1
    assert inv_after["available_qty"] == 0


# ===========================================================================
# boundary_precision_check / loyalty_tier_silver_threshold_exactly_500
# ===========================================================================
def test_loyalty_tier_silver_at_exactly_500_points(api):
    """PRD §3.5: "The thresholds are inclusive lower bounds, so exactly 500 points
    yields `SILVER` while 499 yields `BRONZE`."

    A fulfilled 50000-cent order accrues exactly floor(50000/100) = 500 points,
    landing precisely on the SILVER inclusive lower bound.

    Design: Difficulty/boundary_precision_check/loyalty_tier_silver_threshold_exactly_500
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="APPAREL", name="Coat500", base_price_cents=50000, size_label="L")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 3)

    ready, _ = setup_ready_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    fulfill_order(ready["id"])

    cust_after = get_customer(customer["id"])
    assert cust_after["loyalty_points"] == 500
    assert cust_after["loyalty_tier"] == "SILVER"


def test_loyalty_tier_bronze_just_below_silver_threshold(api):
    """PRD §3.5: "The thresholds are inclusive lower bounds, so exactly 500 points
    yields `SILVER` while 499 yields `BRONZE`."

    A fulfilled 49900-cent order accrues floor(49900/100) = 499 points — one below
    the threshold — so the customer remains BRONZE.

    Design: Difficulty/boundary_precision_check/loyalty_tier_silver_threshold_exactly_500
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="APPAREL", name="Coat499", base_price_cents=49900, size_label="L")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 3)

    ready, _ = setup_ready_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    fulfill_order(ready["id"])

    cust_after = get_customer(customer["id"])
    assert cust_after["loyalty_points"] == 499
    assert cust_after["loyalty_tier"] == "BRONZE"


# ===========================================================================
# boundary_precision_check / inventory_available_exactly_equals_quantity_on_place
# ===========================================================================
def test_place_succeeds_when_available_exactly_equals_quantity(api):
    """PRD §2.5: "A reservation may only proceed when the affected row's
    `available_qty` is at least the number of units requested".
    PRD §3.3: "when every line's target stock row has `available_qty` at least the
    line's `quantity`".

    A SKU stocked with exactly 3 units; an order line of qty 3 places successfully
    (available 3 >= qty 3), leaving available_qty 0.

    Design: Difficulty/boundary_precision_check/inventory_available_exactly_equals_quantity_on_place
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="FOOTWEAR", name="Cleats", base_price_cents=9000, size_label="10.5D")
    customer = create_customer(home_state_code="CA")
    inv = stock_sku(store["id"], sku["id"], 3)

    placed, _ = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 3}]
    )
    assert placed["fulfillment_status"] == "RESERVED"

    inv_after = get_inventory(inv["id"])
    assert inv_after["available_qty"] == 0


def test_place_rejected_when_quantity_exceeds_available_by_one(api):
    """PRD §2.5: "a request that would reserve more than is available is rejected
    with `ERR_INSUFFICIENT_INVENTORY`."
    PRD §3.3: "If any line cannot be covered by available stock, the placement is
    rejected with `ERR_INSUFFICIENT_INVENTORY`."

    With exactly 3 units stocked, a line of qty 4 (available + 1) is rejected — the
    one-above-boundary case.

    Design: Difficulty/boundary_precision_check/inventory_available_exactly_equals_quantity_on_place
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="FOOTWEAR", name="Cleats", base_price_cents=9000, size_label="10.5D")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 3)

    order = create_draft_order(customer["id"], store["id"])
    add_order_line(order["id"], customer["id"], sku["id"], 4)
    res = api.place_order(order["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INSUFFICIENT_INVENTORY", expected_status=409)
