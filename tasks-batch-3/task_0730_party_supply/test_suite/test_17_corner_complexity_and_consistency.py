"""Corner queue — complexity_layers and consistency_model sections.

Excluded stub: cascade_order_return_reconciles_sku_and_credit — owned by
difficulty rule 4 instance A in test_04.
"""
from test_helpers import (
    validate_success, api_client, make_store_clerk_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock,
    setup_draft_order, reserve_order, cancel_order,
)


def test_reserved_qty_reconciles_after_cancel():
    """PRD §2.8: "reserved_qty must at all times reconcile against the
    source of truth: for every SKU, the reserved quantity equals the
    sum of the qty of every OrderLine whose parent Order is in
    fulfillment_status RESERVED, PICKING, or READY_FOR_PICKUP and whose
    sku_id matches that SKU, plus the sum over every such OrderLine
    whose bundle_id matches of BundleLine.qty multiplied by
    OrderLine.qty for every bundle line that names the SKU, plus the
    sum of qty for every RentalContract whose status is RESERVED and
    whose sku_id matches. This reconciliation is recomputed on every
    order reserve, cancellation, pickup, and return."

    Design: Corner/complexity_layers/derived_reserved_qty_reconciles_after_cancel
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=10)
    order = setup_draft_order(cust["id"], sku["id"], qty=4)
    reserve_order(order["id"], order["version"])
    r1 = api_client.get_sku(sku["id"], make_store_clerk_headers())
    after_reserve = validate_success(r1)
    assert after_reserve["reserved_qty"] == 4, (
        f"After reserve of qty=4 line, Sku.reserved_qty must be 4; "
        f"got {after_reserve['reserved_qty']}"
    )
    cancel_order(order["id"])
    r2 = api_client.get_sku(sku["id"], make_store_clerk_headers())
    after_cancel = validate_success(r2)
    assert after_cancel["reserved_qty"] == 0, (
        f"After cancel, Sku.reserved_qty must reconcile back to 0; "
        f"got {after_cancel['reserved_qty']}"
    )


def test_bopis_pickup_deadline_is_pickup_window_end_plus_48h():
    """PRD §2.9: "For a BOPIS order, the pickup deadline is computed at
    reserve time as pickup_window_end plus 48 hours and stored in
    pickup_deadline; the customer must be picked up before the server
    clock reaches this deadline, otherwise the order is swept to
    CANCELLED by the no-show mechanism described in §2.13."

    Design: Corner/complexity_layers/scheduled_action_pickup_deadline_computed_at_reserve
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=5)
    order = setup_draft_order(
        cust["id"], sku["id"], qty=1, channel="BOPIS",
        pickup_window_start="2026-06-15T14:00:00Z",
        pickup_window_end="2026-06-15T18:00:00Z",
    )
    reserved = reserve_order(order["id"], order["version"])
    # pickup_deadline = 2026-06-15T18:00 + 48h = 2026-06-17T18:00.
    # Compare truncated to a stable prefix so we tolerate whichever
    # ISO-8601 fractional-seconds representation the server chose.
    deadline = reserved["pickup_deadline"]
    assert deadline is not None
    assert deadline.startswith("2026-06-17T18:00:00"), (
        f"pickup_deadline for pickup_window_end=2026-06-15T18:00 must be "
        f"2026-06-17T18:00 (+48h); got {deadline}"
    )


def test_reserve_response_carries_recomputed_grand_total_immediately():
    """PRD §3.4: "Order-level fees are recomputed as subtotal_cents,
    helium_fee_cents, delivery_fee_cents, deposit_cents, and
    grand_total_cents."
    PRD §3.4: "grand_total_cents is then subtotal_cents plus
    helium_fee_cents plus delivery_fee_cents plus deposit_cents."

    Design: Corner/consistency_model/reserve_response_reflects_immediate_grand_total_recompute
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=500, on_hand=10)
    order = setup_draft_order(cust["id"], sku["id"], qty=3)
    resp = api_client.reserve_order(
        order["id"], order["version"], make_store_clerk_headers(),
    )
    reserved = validate_success(resp)
    # subtotal = 3 * 500 = 1500; no helium/delivery/deposit → grand_total 1500.
    assert reserved["subtotal_cents"] == 1500, (
        f"Reserve response must expose recomputed subtotal_cents immediately; "
        f"expected 1500, got {reserved['subtotal_cents']}"
    )
    assert reserved["grand_total_cents"] == 1500, (
        f"Reserve response must expose recomputed grand_total_cents immediately; "
        f"expected 1500, got {reserved['grand_total_cents']}"
    )
