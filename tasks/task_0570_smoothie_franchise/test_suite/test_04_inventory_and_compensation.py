"""Inventory FIFO boundary, pay/cancel compensation invariants, and spoilage."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_franchisee, create_store, create_open_store,
    create_ingredient, create_inventory_lot, create_menu_item, create_customer,
    setup_order_env, place_order, pay_order, order_line, set_clock,
    make_customer_headers, make_store_staff_headers,
    create_order_payload,
)


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/inventory_exact_availability_boundary
# ---------------------------------------------------------------------------

def _two_orders_against_150(api):
    fr, st = create_open_store(api)
    ing = create_ingredient(api, name="Mango")
    lot = create_inventory_lot(api, st["id"], ing["id"], qty_received=150, unit_cost_cents=2)
    mi = create_menu_item(api, name="Mango Tango", category="SMOOTHIE", base_price_cents=500,
                          recipe=[{"ingredient_id": ing["id"], "base_qty": 100}], base_calories=200)
    cust = create_customer(api, email="c10@x.com", full_name="C Ten")
    o1 = place_order(api, st["id"], cust["id"], [order_line(mi["id"], "MEDIUM")])
    o2 = place_order(api, st["id"], cust["id"], [order_line(mi["id"], "MEDIUM")])
    return st, cust, lot, o1, o2


def test_pay_at_exact_availability_depletes_lot(api):
    """PRD §3.6: "The boundary is inclusive: a requirement exactly equal to the available
    total succeeds, and a requirement one unit greater fails."
    PRD §3.6: "with any lot whose `remaining_qty` hits 0 moving to `DEPLETED`."

    Design: Difficulty/boundary_precision_check/inventory_exact_availability_boundary
    """
    st, cust, lot, o1, o2 = _two_orders_against_150(api)
    paid = pay_order(api, o1["id"], cust["id"])  # requires 150 == available 150
    assert paid["payment_status"] == "PAID", f"Expected PAID, got {paid['payment_status']}"
    lot_resp = api.get_inventory_lot(lot["id"], make_store_staff_headers(st["id"]))
    lot_after = validate_success(lot_resp)
    assert lot_after["remaining_qty"] == 0, f"Expected remaining 0, got {lot_after['remaining_qty']}"
    assert lot_after["status"] == "DEPLETED", f"Expected DEPLETED, got {lot_after['status']}"


def test_second_pay_over_availability_rejected(api):
    """PRD §3.6: "if the total `remaining_qty` across those lots is less than the
    requirement, payment is rejected with `ERR_INSUFFICIENT_INVENTORY`."

    Design: Difficulty/boundary_precision_check/inventory_exact_availability_boundary
    """
    st, cust, lot, o1, o2 = _two_orders_against_150(api)
    pay_order(api, o1["id"], cust["id"])  # depletes the lot to 0
    resp = api.pay_order(o2["id"], make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/loyalty_points_conserved_on_pay_then_cancel
# ---------------------------------------------------------------------------

def _pay_then_cancel_points(api):
    env = setup_order_env(api, menu={"base_price_cents": 500}, lot={"qty_received": 100})
    st, cust, mi = env["store"], env["customer"], env["menu_item"]
    order = place_order(api, st["id"], cust["id"], [order_line(mi["id"], "SMALL")])
    paid = pay_order(api, order["id"], cust["id"])
    cancelled = validate_success(api.cancel_order(order["id"], make_customer_headers(cust["id"])))
    customer_after = validate_success(api.get_customer(cust["id"], make_customer_headers(cust["id"])))
    return paid, cancelled, customer_after


def test_points_balance_conserved_after_pay_then_cancel(api):
    """PRD §3.6: "The `points_earned` is the floor of `discounted_subtotal_cents` divided
    by 100 — one point per whole dollar of the pre-tax discounted subtotal — and is
    written as an `EARN` points transaction of `+points_earned`, cascading through the
    customer's `points_balance`, `lifetime_points_earned`, and `loyalty_tier`."
    PRD §3.6: "If points were earned, a `CLAWBACK` transaction of `-points_earned` is
    written, lowering the customer's `points_balance` and `lifetime_points_earned` and
    recomputing the `loyalty_tier`."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_on_pay_then_cancel
    """
    paid, cancelled, customer_after = _pay_then_cancel_points(api)
    assert paid["points_earned"] == 5, f"Expected points_earned 5, got {paid['points_earned']}"
    assert customer_after["points_balance"] == 0, (
        f"Expected balance 0 after clawback, got {customer_after['points_balance']}"
    )
    assert customer_after["lifetime_points_earned"] == 0, (
        f"Expected lifetime 0 after clawback, got {customer_after['lifetime_points_earned']}"
    )


def test_payment_refunded_after_cancel(api):
    """PRD §3.6: "it moves `fulfillment → CANCELLED` and, if `payment_status` was `PAID`,
    also moves `payment → REFUNDED`."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_on_pay_then_cancel
    """
    paid, cancelled, customer_after = _pay_then_cancel_points(api)
    assert cancelled["payment_status"] == "REFUNDED", (
        f"Expected REFUNDED, got {cancelled['payment_status']}"
    )


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/inventory_units_conserved_on_pay_then_cancel
# ---------------------------------------------------------------------------

def _pay_then_cancel_inventory(api):
    fr, st = create_open_store(api)
    ing = create_ingredient(api, name="Mango")
    lot = create_inventory_lot(api, st["id"], ing["id"], qty_received=200, unit_cost_cents=2)
    mi = create_menu_item(api, name="Mango Tango", category="SMOOTHIE", base_price_cents=500,
                          recipe=[{"ingredient_id": ing["id"], "base_qty": 100}], base_calories=200)
    cust = create_customer(api, email="c17@x.com", full_name="C Seventeen")
    order = place_order(api, st["id"], cust["id"], [order_line(mi["id"], "MEDIUM")])
    pay_order(api, order["id"], cust["id"])  # consumes 150
    validate_success(api.cancel_order(order["id"], make_customer_headers(cust["id"])))
    lot_after = validate_success(api.get_inventory_lot(lot["id"], make_store_staff_headers(st["id"])))
    return lot_after


def test_inventory_units_restored_after_cancel(api):
    """PRD §3.6: "Inventory is restored: for each unit consumed at payment, the
    originating lot's `remaining_qty` is incremented and its `consumed_qty` decremented,
    and a `DEPLETED` lot returns to `AVAILABLE`."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_on_pay_then_cancel
    """
    lot_after = _pay_then_cancel_inventory(api)
    assert lot_after["remaining_qty"] == 200, (
        f"Expected remaining restored to 200, got {lot_after['remaining_qty']}"
    )
    assert lot_after["consumed_qty"] == 0, (
        f"Expected consumed restored to 0, got {lot_after['consumed_qty']}"
    )


def test_depleted_lot_returns_available_after_cancel(api):
    """PRD §3.6: "Inventory is restored: for each unit consumed at payment, the
    originating lot's `remaining_qty` is incremented and its `consumed_qty` decremented,
    and a `DEPLETED` lot returns to `AVAILABLE`."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_on_pay_then_cancel
    """
    lot_after = _pay_then_cancel_inventory(api)
    assert lot_after["status"] == "AVAILABLE", (
        f"Expected AVAILABLE after restore, got {lot_after['status']}"
    )


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/spoilage_sweep_lot_spoiled_store_cost
# ---------------------------------------------------------------------------

def _spoil_expired_lot(api):
    fr = create_franchisee(api)
    st = create_store(api, fr["id"], catering_capacity=10)  # remains SETUP
    ing = create_ingredient(api, name="Kale", standard_cost_cents_per_unit=3)
    lot = create_inventory_lot(api, st["id"], ing["id"], qty_received=100, unit_cost_cents=5,
                               received_at="2026-05-01T00:00:00Z", expiry_date="2026-05-05T00:00:00Z")
    set_clock(api, "2026-05-10T00:00:00Z")
    validate_success(api.spoilage_sweep(st["id"], make_store_staff_headers(st["id"])))
    lot_after = validate_success(api.get_inventory_lot(lot["id"], make_store_staff_headers(st["id"])))
    store_after = validate_success(api.get_store(st["id"], make_store_staff_headers(st["id"])))
    return lot_after, store_after


def test_spoilage_sweep_marks_lot_spoiled(api):
    """PRD §3.2: "every `AVAILABLE` lot whose `expiry_date` is at or before the current
    logical clock (that is, the clock has reached or passed expiry) transitions
    `AVAILABLE → SPOILED`. For each spoiled lot, its `spoiled_qty` is set to whatever
    `remaining_qty` it had, its `remaining_qty` is then set to 0"

    Design: Difficulty/transitive_cascade/spoilage_sweep_lot_spoiled_store_cost
    """
    lot_after, store_after = _spoil_expired_lot(api)
    assert lot_after["status"] == "SPOILED", f"Expected SPOILED, got {lot_after['status']}"
    assert lot_after["spoiled_qty"] == 100, f"Expected spoiled_qty 100, got {lot_after['spoiled_qty']}"
    assert lot_after["remaining_qty"] == 0, f"Expected remaining 0, got {lot_after['remaining_qty']}"


def test_spoilage_sweep_increments_store_spoilage_cost(api):
    """PRD §3.2: "the write-off — that lot's `spoiled_qty` multiplied by its
    `unit_cost_cents` — is added to the store's `mtd_spoilage_cents`."

    Design: Difficulty/transitive_cascade/spoilage_sweep_lot_spoiled_store_cost
    """
    lot_after, store_after = _spoil_expired_lot(api)
    # spoiled_qty 100 * unit_cost 5 = 500.
    assert store_after["mtd_spoilage_cents"] == 500, (
        f"Expected mtd_spoilage_cents 500, got {store_after['mtd_spoilage_cents']}"
    )


# ---------------------------------------------------------------------------
# Corner/validations/redeem_more_than_balance_returns_insufficient_points
# ---------------------------------------------------------------------------

def test_redeem_more_than_balance_returns_insufficient_points(api):
    """PRD §3.5: "If `redeem_points` exceeds the customer's current `points_balance`, the
    order is rejected with `ERR_INSUFFICIENT_POINTS`."

    Design: Corner/validations/redeem_more_than_balance_returns_insufficient_points
    """
    env = setup_order_env(api)
    st, cust, mi = env["store"], env["customer"], env["menu_item"]
    resp = api.create_order(
        create_order_payload(st["id"], [order_line(mi["id"], "SMALL")], redeem_points=100),
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)
