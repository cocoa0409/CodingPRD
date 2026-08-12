"""Buyer invoice arithmetic (PRD 3.10, 3.11)."""
import config
from money import D, q2
from store import db, get, touch

BILLABLE_PURCHASE_STATUSES = ("CONFIRMED", "INVOICED", "ADJUSTED", "PAID")


def invoice_purchases(invoice_id):
    return sorted([p for p in db["purchases"].values()
                   if p.get("buyer_invoice_id") == invoice_id],
                  key=lambda p: p["_seq"])


def subtotal(invoice):
    total = D(0)
    for purchase in invoice_purchases(invoice["id"]):
        if purchase["status"] in BILLABLE_PURCHASE_STATUSES:
            total += D(purchase["extended_amount"])
    return q2(total)


def invoiced_head(invoice):
    head = 0
    for purchase in invoice_purchases(invoice["id"]):
        if purchase["status"] in BILLABLE_PURCHASE_STATUSES:
            head += purchase["head_count"]
    return head


def buyer_side_fee(invoice):
    """Dual variant selected by the buyer's bond_type."""
    reg = get("buyer_registrations", invoice["buyer_registration_id"])
    bond_type = reg["bond_type"] if reg else "UNSECURED"
    if bond_type == "CASH_ONLY":
        raw = q2(config.CASH_HANDLING_PER_HEAD * D(invoiced_head(invoice)))
        return raw if raw > config.CASH_HANDLING_MIN else config.CASH_HANDLING_MIN
    raw = q2(D(invoice["subtotal"]) * config.BOND_PROCESSING_PCT)
    return raw if raw < config.BOND_FEE_CAP else config.BOND_FEE_CAP


def recompute_totals(invoice):
    """total_due = subtotal + buyer_fee - credit_memo_total;
    balance_due = total_due - amount_paid."""
    invoice["total_due"] = q2(D(invoice["subtotal"]) + D(invoice["buyer_fee"])
                              - D(invoice["credit_memo_total"]))
    invoice["balance_due"] = q2(D(invoice["total_due"]) - D(invoice["amount_paid"]))
    touch(invoice)
    return invoice


def recompute_subtotal_only(invoice):
    invoice["subtotal"] = subtotal(invoice)
    recompute_totals(invoice)
    return invoice


def recompute_full(invoice):
    """subtotal, buyer_fee, total_due and balance_due (cascade hop 4 of a
    purchase void, and the interposed invoicing step)."""
    invoice["subtotal"] = subtotal(invoice)
    invoice["buyer_fee"] = buyer_side_fee(invoice)
    recompute_totals(invoice)
    return invoice


def find_or_create_invoice(reg, sale_day_id, insert_versioned):
    """"If the buyer has no invoice yet for this sale day, one is created at
    DRAFT." A VOIDED invoice does not count as an invoice the buyer has: VOIDED
    is terminal with every money field driven to zero, so reusing it would
    leave the new purchase permanently unbillable - the invoice could never
    reach ISSUED, its purchases could never reach INVOICED or PAID, and the
    lot could never clear the gate. We therefore look past voided rows."""
    for invoice in sorted(db["buyer_invoices"].values(), key=lambda r: r["_seq"]):
        if invoice["buyer_registration_id"] == reg["id"] \
                and invoice["sale_day_id"] == sale_day_id \
                and invoice["status"] != "VOIDED":
            return invoice
    return insert_versioned("buyer_invoices", {
        "buyer_registration_id": reg["id"],
        "sale_day_id": sale_day_id,
        "subtotal": q2(0),
        "buyer_fee": q2(0),
        "credit_memo_total": q2(0),
        "total_due": q2(0),
        "amount_paid": q2(0),
        "balance_due": q2(0),
        "status": "DRAFT",
    })
