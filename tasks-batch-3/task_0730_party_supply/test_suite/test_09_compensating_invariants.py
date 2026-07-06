"""Difficulty rule 9 — compensating-action invariants across different
conserved quantities.

Instance A: SKU on_hand — pickup (-qty) then return (+qty) restores stock.
Instance B: helium remaining_cubic_ft — reserve (debit) then cancel (refund).
"""
from test_helpers import (
    validate_success, api_client, make_store_clerk_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock, create_helium_tank,
    setup_draft_order, attach_helium, reserve_order, pay_order,
    start_picking, mark_ready, pickup, cancel_order,
)


# =====================================================================
# Instance A — sku_on_hand_conserved_pickup_then_return
# =====================================================================

def test_pickup_debits_on_hand_qty_by_line_qty():
    """PRD §3.5: "Pickup cascades: for every order line, reserved_qty on
    the referenced SKU decreases by the line quantity and on_hand_qty
    decreases by the same amount, and for every attached RentalContract
    whose status is RESERVED the contract's status becomes PICKED_UP
    while additionally decreasing both reserved_qty and on_hand_qty on
    the rental's SKU by the contract's qty."

    Design: Difficulty/compensating_invariant/sku_on_hand_conserved_pickup_then_return
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=100,
                                 category="BALLOON_LATEX")
    order = setup_draft_order(
        cust["id"], sku["id"], qty=7, channel="BOPIS",
        pickup_window_start="2026-06-15T14:00:00Z",
        pickup_window_end="2026-06-15T18:00:00Z",
    )
    reserved = reserve_order(order["id"], order["version"])
    pay_order(reserved["id"], "FULL")
    start_picking(reserved["id"])
    mark_ready(reserved["id"])
    pickup(reserved["id"])
    r = api_client.get_sku(sku["id"], make_store_clerk_headers())
    after = validate_success(r)
    assert after["on_hand_qty"] == 93, (
        f"Pickup with line qty=7 must debit on_hand_qty 100→93; "
        f"got {after['on_hand_qty']}"
    )


def test_return_restores_on_hand_qty_conserving_stock():
    """PRD §3.5: "Returning transitions PICKED_UP or DELIVERED to
    RETURNED and is permitted only if the server clock is on or before
    the pickup timestamp plus fourteen days and if no line's SKU carries
    is_clearance true — clearance items cannot be returned per §3.1. On
    success, on_hand_qty for each line's SKU is restored by the line
    quantity, payment_status flips from PAID to REFUNDED (or to
    PARTIALLY_REFUNDED if only part of the amount is refunded), and
    store_credit_cents on the customer is credited with the returned
    grand_total_cents."

    Design: Difficulty/compensating_invariant/sku_on_hand_conserved_pickup_then_return
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=100,
                                 category="BALLOON_LATEX")
    order = setup_draft_order(
        cust["id"], sku["id"], qty=7, channel="BOPIS",
        pickup_window_start="2026-06-15T14:00:00Z",
        pickup_window_end="2026-06-15T18:00:00Z",
    )
    reserved = reserve_order(order["id"], order["version"])
    pay_order(reserved["id"], "FULL")
    start_picking(reserved["id"])
    mark_ready(reserved["id"])
    pickup(reserved["id"])
    r_ret = api_client.return_order(reserved["id"], make_store_clerk_headers())
    validate_success(r_ret)
    r_sku = api_client.get_sku(sku["id"], make_store_clerk_headers())
    after_return = validate_success(r_sku)
    assert after_return["on_hand_qty"] == 100, (
        f"Return must restore line qty (+7) — on_hand_qty conserved 93→100; "
        f"got {after_return['on_hand_qty']}"
    )


# =====================================================================
# Instance B — helium_cubic_ft_conserved_reserve_then_cancel
# =====================================================================

def test_helium_reserve_debits_active_tank():
    """PRD §2.10: "Helium is drawn from physical tanks in a deterministic
    waterfall. When an Order is reserved and has an attached HeliumOrder,
    the server computes the required cubic feet as latex_count times
    half a cubic foot plus foil_count times one and a half cubic feet,
    then draws from HeliumTank rows with status equal to ACTIVE in
    ascending order of created_at; ties on created_at are broken by
    tank_code in ascending alphabetical order, never by id. The current
    tank is exhausted before the next is touched: for each tank the
    server takes the smaller of the tank's remaining_cubic_ft and the
    residual required amount, appends the tank's id to helium_tank_ids
    on the HeliumOrder, and decrements remaining_cubic_ft accordingly."

    Design: Difficulty/compensating_invariant/helium_cubic_ft_conserved_reserve_then_cancel
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=10, category="DECOR")
    tank = create_helium_tank(capacity=50)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    attach_helium(order["id"], latex_count=20, foil_count=4)
    reserve_order(order["id"], order["version"])
    # required = 20 * 0.5 + 4 * 1.5 = 10 + 6 = 16 cubic feet.
    r = api_client.get_helium_tank(tank["id"], make_store_clerk_headers())
    after = validate_success(r)
    assert after["remaining_cubic_ft"] == 34, (
        f"Tank must debit 16 cu.ft (20*0.5+4*1.5); remaining 50-16=34; "
        f"got {after['remaining_cubic_ft']}"
    )


def test_helium_cancel_refunds_source_tank_to_original_level():
    """PRD §3.5: "Cancellation from DRAFT, RESERVED, or PICKING moves
    the fulfillment axis to CANCELLED. On success, reserved_qty on every
    referenced SKU is decremented, any helium allocation is returned by
    adding it back to the source tanks' remaining_cubic_ft, any attached
    DeliverySlot flips from RESERVED to CANCELLED, payment_status flips
    from DEPOSIT_HELD to REFUNDED when a deposit was held, and version
    increments."

    Design: Difficulty/compensating_invariant/helium_cubic_ft_conserved_reserve_then_cancel
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=10, category="DECOR")
    tank = create_helium_tank(capacity=50)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    attach_helium(order["id"], latex_count=20, foil_count=4)
    reserved = reserve_order(order["id"], order["version"])
    cancel_order(reserved["id"])
    r = api_client.get_helium_tank(tank["id"], make_store_clerk_headers())
    after = validate_success(r)
    assert after["remaining_cubic_ft"] == 50, (
        f"Cancel must return 16 cu.ft back to source tank; "
        f"expected 50, got {after['remaining_cubic_ft']}"
    )
