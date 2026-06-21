"""Sale closing cascades and money movement.

Covers:
  - creating an Order + its SellerFeeInvoice (PRD §3.6, §3.7)
  - paying an order (PRD §3.8)
  - the refund cascade: full / partial (PRD §3.10)
  - crediting the fee invoice on unwind (PRD §3.7)
"""
import db
import constants as C
from services import core, calc


def create_order_and_invoice(listing, buyer_account_id, source, item_price_cents,
                             shipping_cents):
    """Mint an Order from a sold listing and cascade a SellerFeeInvoice.

    PRD §3.6: order copies listing_id, sets buyer, copies seller from listing,
    records source, snapshots item_price_cents; shipping defaults 0; total =
    item + shipping; payment_status UNPAID, fulfillment_status AWAITING_PAYMENT,
    paid_amount_cents 0.
    PRD §3.7: each order creation cascades exactly one SellerFeeInvoice.
    """
    if shipping_cents is None:
        shipping_cents = 0

    oid = db.new_id()
    order = {
        "id": oid,
        "listing_id": listing["id"],
        "buyer_account_id": buyer_account_id,
        "seller_account_id": listing["seller_account_id"],
        "source": source,
        "item_price_cents": item_price_cents,
        "shipping_cents": shipping_cents,
        "total_cents": item_price_cents + shipping_cents,
        "payment_status": "UNPAID",
        "fulfillment_status": "AWAITING_PAYMENT",
        "paid_amount_cents": 0,
        "delivered_at": None,  # internal: records DELIVERED time for return window
    }
    core.stamp_new(order)
    db.orders[oid] = order

    # Cascade SellerFeeInvoice
    seller_id = listing["seller_account_id"]
    amount = calc.seller_fvf(item_price_cents)
    iid = db.new_id()
    invoice = {
        "id": iid,
        "order_id": oid,
        "seller_account_id": seller_id,
        "gross_item_cents": item_price_cents,
        "fvf_rate_basis_points": calc.fvf_rate_basis_points(item_price_cents),
        "amount_cents": amount,
        "settlement_status": "INVOICED",
    }
    core.stamp_new(invoice)
    db.seller_fee_invoices[iid] = invoice

    # Recompute seller balance/standing now that a new INVOICED invoice exists.
    core.recompute_account_fee_balance(seller_id)
    return order


def invoice_for_order(order_id):
    for inv in db.seller_fee_invoices.values():
        if inv["order_id"] == order_id:
            return inv
    return None


def credit_invoice(order):
    """Credit the order's fee invoice (INVOICED -> CREDITED). PRD §3.7.

    Recomputes seller fee balance/standing and bumps the invoice version.
    Only an INVOICED invoice is credited (PAID/CREDITED left as-is).
    """
    inv = invoice_for_order(order["id"])
    if inv is None:
        return
    if inv["settlement_status"] == "INVOICED":
        inv["settlement_status"] = "CREDITED"
        core.touch(inv)
        core.recompute_account_fee_balance(inv["seller_account_id"])


def recompute_invoice_on_partial(order, new_gross):
    """Partial refund: recompute the fee invoice amount on the reduced gross,
    not credited. PRD §3.7 / §3.10.
    """
    inv = invoice_for_order(order["id"])
    if inv is None:
        return
    if inv["settlement_status"] == "INVOICED":
        inv["gross_item_cents"] = new_gross
        inv["fvf_rate_basis_points"] = calc.fvf_rate_basis_points(new_gross)
        inv["amount_cents"] = calc.seller_fvf(new_gross)
        core.touch(inv)
        core.recompute_account_fee_balance(inv["seller_account_id"])


def append_payment(order_id, kind, amount_cents):
    """Append an immutable Payment event. PRD §2.4, §3.8."""
    pid = db.new_id()
    payment = {
        "id": pid,
        "order_id": order_id,
        "kind": kind,
        "amount_cents": amount_cents,
    }
    core.stamp_new(payment, with_version=False)
    db.payments[pid] = payment
    return payment


def apply_refund(order, refund_amount):
    """Apply a refund cascade against the order's current paid_amount_cents.

    PRD §3.10:
      full refund (refund == paid_amount_cents): append REFUND for full amount,
        paid_amount_cents -> 0, payment_status -> REFUNDED, credit fee invoice.
      partial refund (0 < refund < paid_amount_cents): append REFUND for amount,
        paid_amount_cents -= amount, payment_status -> PARTIALLY_REFUNDED,
        recompute fee invoice on reduced gross.

    Bumps the order version once (caller relies on this).
    Does not bump for refund==0 (caller handles no-refund branch separately).
    """
    paid = order["paid_amount_cents"]
    if refund_amount <= 0:
        return
    if refund_amount >= paid:
        # Full refund
        append_payment(order["id"], "REFUND", paid)
        order["paid_amount_cents"] = 0
        order["payment_status"] = "REFUNDED"
        core.touch(order)
        credit_invoice(order)
    else:
        # Partial refund
        append_payment(order["id"], "REFUND", refund_amount)
        order["paid_amount_cents"] = paid - refund_amount
        order["payment_status"] = "PARTIALLY_REFUNDED"
        # New gross = reduced item base. The refund reduces the item value;
        # recompute the fee on the remaining item portion of paid amount.
        # PRD §3.10: "recomputes the seller fee invoice's amount_cents against the
        # reduced gross". The reduced gross is the order's item price minus the
        # refunded portion attributable to the item. We treat the refund as
        # reducing the gross item amount directly.
        inv = invoice_for_order(order["id"])
        if inv is not None:
            new_gross = max(0, inv["gross_item_cents"] - refund_amount)
            recompute_invoice_on_partial(order, new_gross)
        core.touch(order)
