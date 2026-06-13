"""Invoice balance, ledger posting, and autopay cascade (PRD §3.6)."""
from db import db, new_id, now_iso
from common import touch


def invoice_balance(invoice):
    """Recompute the invoice balance from ledger + captured payments."""
    inv_id = invoice["id"]
    entries = [e for e in db.ledger_entries.values() if e["invoice_id"] == inv_id]
    charges = sum(e["amount_cents"] for e in entries if e["kind"] == "CHARGE")
    credits = sum(e["amount_cents"] for e in entries if e["kind"] == "CREDIT")
    payments = sum(p["amount_cents"] for p in db.payments.values()
                   if p["invoice_id"] == inv_id and p["status"] == "CAPTURED")
    return charges - credits - payments


def post_ledger_entry(invoice, kind, reason, amount_cents, source_ref):
    """Append-only ledger entry; bumps the invoice version/updated_at."""
    eid = new_id()
    entry = {
        "id": eid,
        "invoice_id": invoice["id"],
        "kind": kind,
        "reason": reason,
        "amount_cents": amount_cents,
        "source_ref": source_ref,
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.ledger_entries[eid] = entry
    # Invoice totals are computed fields; posting an entry mutates the invoice.
    touch(invoice)
    return entry


def capture_autopay(agreement, invoice):
    """After a charge posts, if autopay is on and balance>0, capture the balance."""
    if not agreement.get("autopay_enabled"):
        return None
    balance = invoice_balance(invoice)
    if balance > 0:
        pid = new_id()
        payment = {
            "id": pid,
            "facility_id": invoice["facility_id"],
            "invoice_id": invoice["id"],
            "amount_cents": balance,
            "method": "CARD_AUTOPAY",
            "status": "CAPTURED",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.payments[pid] = payment
        touch(invoice)
        return payment
    return None


def settle_if_paid(invoice):
    """Move an OPEN invoice to SETTLED once balance <= 0."""
    if invoice["status"] == "OPEN" and invoice_balance(invoice) <= 0:
        invoice["status"] = "SETTLED"
        touch(invoice)
