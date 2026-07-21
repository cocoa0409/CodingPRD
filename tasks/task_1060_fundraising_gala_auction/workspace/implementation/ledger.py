"""Shared invoice/settlement helpers used by the auction and money routes."""
import calc
from core import db, new_row, rows, touch


def find_or_create_open_invoice(event_id, bidder_id):
    for inv in rows("invoices"):
        if inv["event_id"] == event_id and inv["bidder_id"] == bidder_id \
                and inv["status"] == "OPEN":
            return inv
    inv = new_row(event_id=event_id, bidder_id=bidder_id, cover_processing_fee=False,
                  line_items=[], line_subtotal_cents=0, processing_fee_cents=0,
                  total_due_cents=0, amount_paid_cents=0, balance_due_cents=0,
                  status="OPEN")
    db.invoices[inv["id"]] = inv
    return inv


def settle_paid(invoice):
    """Cascade run when an invoice reaches PAID."""
    for item in rows("items"):
        if item["invoice_id"] == invoice["id"] and item["settlement_status"] == "INVOICED":
            item["settlement_status"] = "PAID"
            touch(item)
    for gift in rows("paddles"):
        if gift["invoice_id"] == invoice["id"] and gift["settlement_status"] == "INVOICED":
            gift["settlement_status"] = "PAID"
            touch(gift)
    for order in rows("orders"):
        if order["invoice_id"] == invoice["id"] and order["payment_status"] == "INVOICED":
            order["payment_status"] = "PAID"
            touch(order)


def unsettle_paid(invoice):
    """Compensating cascade run when a PAID invoice loses money."""
    for item in rows("items"):
        if item["invoice_id"] == invoice["id"] and item["settlement_status"] == "PAID":
            item["settlement_status"] = "INVOICED"
            touch(item)
    for gift in rows("paddles"):
        if gift["invoice_id"] == invoice["id"] and gift["settlement_status"] == "PAID":
            gift["settlement_status"] = "INVOICED"
            touch(gift)
    for order in rows("orders"):
        if order["invoice_id"] == invoice["id"] and order["payment_status"] == "PAID":
            order["payment_status"] = "INVOICED"
            touch(order)


def detach_lots(invoice):
    """Revert only auction lots (used when voiding an OPEN invoice)."""
    for item in rows("items"):
        if item["invoice_id"] == invoice["id"] and item["settlement_status"] == "INVOICED":
            item["settlement_status"] = "UNSETTLED"
            item["invoice_id"] = None
            touch(item)


def detach_all(invoice):
    """Revert lots, gifts and ticket orders (used when voiding a finalized invoice)."""
    detach_lots(invoice)
    for gift in rows("paddles"):
        if gift["invoice_id"] == invoice["id"] and gift["settlement_status"] == "INVOICED":
            gift["settlement_status"] = "UNSETTLED"
            gift["invoice_id"] = None
            touch(gift)
    for order in rows("orders"):
        if order["invoice_id"] == invoice["id"] and order["payment_status"] == "INVOICED":
            order["payment_status"] = "UNBILLED"
            order["invoice_id"] = None
            touch(order)


def bump_bidder(bidder_id):
    bidder = db.bidders.get(bidder_id)
    if bidder is not None:
        calc.recompute_bidder(bidder)


def bump_event(event_id):
    event = db.events.get(event_id)
    if event is not None:
        calc.recompute_event(event)
