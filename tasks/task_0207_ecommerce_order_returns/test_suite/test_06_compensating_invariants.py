"""Compensating-action invariants (PRD §3.4 / §3.8).

Difficulty queue: compensating_invariant (checkout→void conserves units;
capture→full cash refund conserves net payment).
"""
from test_helpers import fixtures as fx

DELIVER_CLOCK = "2026-06-05T00:00:00Z"
ACT_CLOCK = "2026-06-10T00:00:00Z"


def test_checkout_reserves_available_units(api):
    """PRD §3.3: "Each touched InventoryItem then has its reserved_qty and
    available_qty recomputed."
    PRD §3.1: "available_qty, equal to on_hand_qty minus reserved_qty and floored at
    0 — the quantity reservable right now."

    Design: Difficulty/compensating_invariant/checkout_then_void_conserves_inventory_available_units
    """
    ctx = fx.setup_authorized_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=4, on_hand_qty=10)
    inv = fx.get_inventory(ctx["inventory"]["id"])
    assert inv["available_qty"] == 6, "10 on_hand - 4 reserved"


def test_void_releases_holds_restoring_available_to_pre_checkout(api):
    """PRD §3.4: "Voiding releases every HELD reservation belonging to the order,
    transitioning each from HELD to RELEASED; this is the compensation for the hold
    taken at checkout, returning the held quantity to each touched InventoryItem's
    available_qty (the physical on_hand_qty is unchanged because nothing ever
    shipped)."

    Design: Difficulty/compensating_invariant/checkout_then_void_conserves_inventory_available_units
    """
    ctx = fx.setup_authorized_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=4, on_hand_qty=10)
    inv_after_checkout = fx.get_inventory(ctx["inventory"]["id"])
    assert inv_after_checkout["available_qty"] == 6

    fx.get_success_data(api.void_order(ctx["order"]["id"], fx.ADMIN))

    inv_after_void = fx.get_inventory(ctx["inventory"]["id"])
    assert inv_after_void["available_qty"] == 10, \
        "compensation restores the conserved available-unit count"
    assert inv_after_void["on_hand_qty"] == 10, \
        "void never decremented on_hand (no ship occurred)"


def test_capture_freezes_captured_total(api):
    """PRD §3.4: "it freezes the captured base by setting captured_total_cents to the
    current grand_total_cents".

    Design: Difficulty/compensating_invariant/capture_then_full_cash_refund_conserves_net_payment_to_zero
    """
    ctx = fx.setup_captured_order(
        product_overrides={"unit_price_cents": 10000, "tax_rate_bps": 0,
                           "restocking_fee_bps": 0, "return_window_days": 30},
        qty=1, on_hand_qty=10)
    order = fx.get_order(ctx["order"]["id"])
    assert order["captured_total_cents"] == 10000, "grand_total 10000 frozen at capture"


def test_full_cash_refund_returns_order_to_refunded(api):
    """PRD §3.8: "When the destination is ORIGINAL_PAYMENT, the order's payment
    dimension bubbles up: if the cumulative amount_cents of ORIGINAL_PAYMENT refunds
    for the order is still less than captured_total_cents the order moves to
    PARTIALLY_REFUNDED, and when that cumulative total reaches captured_total_cents
    the order moves to REFUNDED."

    Design: Difficulty/compensating_invariant/capture_then_full_cash_refund_conserves_net_payment_to_zero
    """
    fx.set_clock(DELIVER_CLOCK)
    ctx = fx.setup_delivered_order(
        product_overrides={"unit_price_cents": 10000, "tax_rate_bps": 0,
                           "restocking_fee_bps": 0, "return_window_days": 30},
        qty=1, on_hand_qty=10, delivered_clock=DELIVER_CLOCK)
    fx.set_clock(ACT_CLOCK)
    rma = fx.open_approve_settle_return(
        ctx["order"]["id"], ctx["customer"]["id"], "DEFECTIVE", "REFUND",
        [{"order_line_id": ctx["line"]["id"], "return_qty": 1}])

    refunds = fx.list_return_refunds(rma["id"])
    assert refunds[0]["amount_cents"] == 10000, \
        "DEFECTIVE waives restock; tax 0; shipping not refunded but was 0"

    order_after = fx.get_order(ctx["order"]["id"])
    assert order_after["payment_status"] == "REFUNDED", \
        "cumulative ORIGINAL_PAYMENT refund == captured_total → net 0"
