"""Difficulty rule 4 — transitive cascades from different triggers.

Instance A: depth-3 Order pickup → RentalContract PICKED_UP; then
RentalContract return → Sku.on_hand_qty += qty AND
Customer.store_credit_cents += deposit.
Instance B: depth-2 CustomPrintOrder approve → pin print_fee →
Order.subtotal recomputed → Order.grand_total recomputed.
"""
from test_helpers import (
    validate_success, api_client, make_store_clerk_headers,
    make_customer_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock,
    setup_draft_order, create_rental_contract,
    reserve_order, pay_order, start_picking, mark_ready, pickup,
    attach_custom_print,
)


# =====================================================================
# Instance A — order_pickup_rental_pickup_return_credit_chain
# =====================================================================

def _setup_bopis_order_with_rental_to_pickup():
    """Build a BOPIS order with a rental attached, then take Order to
    PICKED_UP. Returns (customer, plate_sku, order_after_pickup, rental)."""
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    plate = create_sku_with_stock(unit_price_cents=500, on_hand=20,
                                   category="TABLEWARE")
    order = setup_draft_order(
        cust["id"], plate["id"], qty=1, channel="BOPIS",
        pickup_window_start="2026-06-15T14:00:00Z",
        pickup_window_end="2026-06-15T18:00:00Z",
    )
    rental = create_rental_contract(
        order["id"], plate["id"], qty=6,
        rental_start="2026-06-16T00:00:00Z",
        rental_end="2026-06-20T00:00:00Z",
    )
    reserved = reserve_order(order["id"], order["version"])
    pay_order(reserved["id"], "FULL")
    start_picking(reserved["id"])
    mark_ready(reserved["id"])
    pickup(reserved["id"])
    return cust, plate, rental


def test_order_pickup_cascades_rental_to_picked_up_and_debits_on_hand():
    """PRD §3.5: "Pickup cascades: for every order line, reserved_qty on
    the referenced SKU decreases by the line quantity and on_hand_qty
    decreases by the same amount, and for every attached RentalContract
    whose status is RESERVED the contract's status becomes PICKED_UP
    while additionally decreasing both reserved_qty and on_hand_qty on
    the rental's SKU by the contract's qty."

    Design: Difficulty/transitive_cascade/order_pickup_rental_pickup_return_credit_chain
    """
    cust, plate, rental = _setup_bopis_order_with_rental_to_pickup()
    # After pickup: OrderLine qty=1 → on_hand -=1; Rental qty=6 → on_hand -=6.
    # Starting on_hand=20 → after pickup 20 - 1 - 6 = 13.
    r_plate = api_client.get_sku(plate["id"], make_store_clerk_headers())
    plate_after = validate_success(r_plate)
    assert plate_after["on_hand_qty"] == 13, (
        f"on_hand_qty after pickup with 1-line + rental qty=6 must be "
        f"20 - 1 - 6 = 13; got {plate_after['on_hand_qty']}"
    )
    r_rental = api_client.get_rental_contract(
        rental["id"], make_store_clerk_headers()
    )
    rental_after = validate_success(r_rental)
    assert rental_after["status"] == "PICKED_UP", (
        f"RentalContract must be PICKED_UP after parent Order pickup; "
        f"got {rental_after['status']}"
    )


def test_rental_return_on_time_credits_customer_and_restores_stock():
    """PRD §3.6: "A return-marking action while the server clock is
    strictly before rental_end transitions the contract to RETURNED,
    sets returned_at to the current server clock, adds qty back to the
    SKU's on_hand_qty, and credits the customer's store_credit_cents by
    the contract's deposit_cents."

    Design: Difficulty/transitive_cascade/order_pickup_rental_pickup_return_credit_chain
    """
    cust, plate, rental = _setup_bopis_order_with_rental_to_pickup()
    # Advance clock but stay strictly before rental_end (2026-06-20).
    set_clock("2026-06-18T12:00:00Z")
    r_ret = api_client.return_rental(rental["id"], make_store_clerk_headers())
    returned = validate_success(r_ret)
    assert returned["status"] == "RETURNED"
    # deposit_cents = 2 * 500 * 6 = 6000.
    assert returned["deposit_cents"] == 6000
    # Stock: 13 (post-pickup) + 6 (rental return) = 19.
    r_plate = api_client.get_sku(plate["id"], make_store_clerk_headers())
    plate_after = validate_success(r_plate)
    assert plate_after["on_hand_qty"] == 19, (
        f"on_hand_qty after on-time rental return must add back 6; "
        f"expected 13+6=19, got {plate_after['on_hand_qty']}"
    )
    # store_credit_cents credited with rental deposit 6000.
    r_cust = api_client.get_customer(cust["id"], make_store_clerk_headers())
    cust_after = validate_success(r_cust)
    assert cust_after["store_credit_cents"] == 6000, (
        f"store_credit_cents after on-time rental return must be 6000; "
        f"got {cust_after['store_credit_cents']}"
    )


# =====================================================================
# Instance B — custom_print_approve_subtotal_grand_total_recompute
# =====================================================================

def test_custom_print_approve_pins_print_fee():
    """PRD §3.7: "The finalised variant runs at approve time and uses the
    actual observed revision_count; the result is written to
    CustomPrintOrder.print_fee_cents, and the parent order's
    subtotal_cents and grand_total_cents are then recomputed to include
    it."

    Design: Difficulty/transitive_cascade/custom_print_approve_subtotal_grand_total_recompute
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=200, on_hand=50, category="DECOR")
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    cpo = attach_custom_print(order["id"], banner_length_ft=3)
    reserved = reserve_order(order["id"], order["version"])
    pay_order(reserved["id"], "FULL")
    api_client.send_proof(cpo["id"], make_store_clerk_headers())
    r_ap = api_client.approve_proof(
        cpo["id"], make_customer_headers(cust["id"])
    )
    approved = validate_success(r_ap)
    # 3-ft banner: 3*800 = 2400 unrounded, no revision surcharge → 2400.
    assert approved["print_fee_cents"] == 2400, (
        f"3-ft banner print_fee_cents must be 3*800=2400; "
        f"got {approved['print_fee_cents']}"
    )


def test_order_subtotal_and_grand_total_recomputed_after_custom_print_approve():
    """PRD §3.4: "if a CustomPrintOrder is attached and not cancelled,
    its print_fee_cents is added to subtotal_cents."
    PRD §3.4: "grand_total_cents is then subtotal_cents plus
    helium_fee_cents plus delivery_fee_cents plus deposit_cents."
    PRD §3.7: "the parent order's subtotal_cents and grand_total_cents
    are then recomputed to include it."

    Design: Difficulty/transitive_cascade/custom_print_approve_subtotal_grand_total_recompute
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=200, on_hand=50, category="DECOR")
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    cpo = attach_custom_print(order["id"], banner_length_ft=3)
    reserved = reserve_order(order["id"], order["version"])
    # Baseline before approve: subtotal 1*200 = 200; grand_total 200.
    assert reserved["subtotal_cents"] == 200
    assert reserved["grand_total_cents"] == 200
    pay_order(reserved["id"], "FULL")
    api_client.send_proof(cpo["id"], make_store_clerk_headers())
    api_client.approve_proof(cpo["id"], make_customer_headers(cust["id"]))
    r_ord = api_client.get_order(order["id"], make_store_clerk_headers())
    ord_after = validate_success(r_ord)
    # print_fee 3*800=2400; subtotal 200+2400=2600; grand_total 2600.
    assert ord_after["subtotal_cents"] == 2600, (
        f"subtotal_cents after approve must be 200+2400=2600; "
        f"got {ord_after['subtotal_cents']}"
    )
    assert ord_after["grand_total_cents"] == 2600, (
        f"grand_total_cents after approve must be 2600; "
        f"got {ord_after['grand_total_cents']}"
    )
