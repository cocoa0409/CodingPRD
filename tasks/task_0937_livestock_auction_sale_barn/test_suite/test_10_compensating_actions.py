"""The purchase-void unwind and the money it puts back."""

from test_helpers import (
    SETTLEMENT_CLERK,
    add_buyer,
    assert_money,
    hammer_lot,
    open_the_ring,
    read_bid,
    read_buyer_invoice,
    read_buyer_registration,
    read_consignment,
    read_lot,
    read_purchase,
    read_sale_day,
    setup_ready_lot,
    validate_success,
)


def _hammered_lot_with_the_pre_sale_reading():
    scn = setup_ready_lot(head_received=10, head_count=10)
    add_buyer(scn, bond_type="BONDED", credit_limit=50000)
    open_the_ring(scn)
    scn.gross_before_the_hammer = read_sale_day(scn.sale_day["id"])["total_gross_sale_value"]
    hammer_lot(scn, unit_price=182.50)
    return scn


def test_voiding_a_purchase_unwinds_the_sale_on_the_lot_and_the_bid(api):
    """PRD §3.11: "Hop 1 takes the purchase to `VOIDED`. Hop 2, caused by hop 1,
    reverses the sale on the lot: `sale_status` moves `SOLD → NO_SALE`, `custody_status`
    moves `BUYER_PEN → BARN` on the parallel axis, `hammer_price` is cleared to null and
    `extended_amount` to zero, the `HAMMERED` bid transitions to `VOIDED`, and the
    next-highest bid standing at `OUTBID` on that lot, if any, is restored to `WINNING`."

    Design: Difficulty/compensating_invariant/purchase_void_restores_sale_day_gross_sale_value_to_zero
    """
    scn = _hammered_lot_with_the_pre_sale_reading()
    assert_money(
        read_lot(scn.lot["id"])["extended_amount"],
        12391.75,
        "the hammer put money on the lot:",
    )

    data = validate_success(
        api.void_purchase(
            scn.purchase["id"],
            {"reason": "Buyer refused the load at the scale"},
            SETTLEMENT_CLERK,
        )
    )
    assert data["status"] == "VOIDED"
    assert read_purchase(scn.purchase["id"])["status"] == "VOIDED"

    lot = read_lot(scn.lot["id"])
    assert lot["sale_status"] == "NO_SALE"
    assert lot["custody_status"] == "BARN"
    assert lot["hammer_price"] is None
    assert_money(lot["extended_amount"], 0.00, "the extension is cleared:")
    assert read_bid(scn.bid["id"])["status"] == "VOIDED"


def test_voiding_a_purchase_puts_the_money_and_the_head_back(api):
    """PRD §3.11: "An invoice all of whose purchases have been voided itself
    transitions to `VOIDED` from `DRAFT`, `ISSUED` or `PARTIALLY_PAID`, with `subtotal`,
    `buyer_fee`, `total_due` and `balance_due` all falling to zero; any `amount_paid`
    already recorded stays on the row as an overpayment."
    PRD §3.11: "Hop 3, caused by hop 2, makes the parent consignment recompute
    `head_sold` and `head_no_saled`, and — when a settlement already exists for that
    consignment — makes that settlement recompute its `gross_amount` and transition to
    `ADJUSTED`."
    PRD §3.10: "`total_gross_sale_value` from the `extended_amount` of its `SOLD` lots"
    PRD §2.10: "A sale day's `gross_match_ok` is true when the total `subtotal` across
    its buyer invoices equals the total `gross_amount` across the settlements of its
    consignments."

    Design: Difficulty/compensating_invariant/purchase_void_restores_sale_day_gross_sale_value_to_zero
    """
    scn = _hammered_lot_with_the_pre_sale_reading()
    validate_success(
        api.void_purchase(
            scn.purchase["id"],
            {"reason": "Buyer refused the load at the scale"},
            SETTLEMENT_CLERK,
        )
    )

    invoice = read_buyer_invoice(scn.invoice["id"])
    assert_money(invoice["subtotal"], 0.00, "the invoice keeps no residue of the sale:")
    assert invoice["status"] == "VOIDED"

    registration = read_buyer_registration(scn.registration["id"])
    assert_money(registration["exposure"], 0.00, "the buyer's exposure is released:")
    assert_money(registration["available_credit"], 75000.00, "the whole line is back:")

    consignment = read_consignment(scn.consignment["id"])
    assert consignment["head_sold"] == 0
    assert consignment["head_no_saled"] == 10

    sale_day = read_sale_day(scn.sale_day["id"])
    assert_money(
        sale_day["total_gross_sale_value"],
        scn.gross_before_the_hammer,
        "the day's gross sale value returns to its pre-hammer reading:",
    )
    assert sale_day["gross_match_ok"] is True
