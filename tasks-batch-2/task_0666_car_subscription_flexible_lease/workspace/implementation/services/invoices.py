"""Invoice posting (PRD §3.14). Invoices are immutable: id + created_at only."""
from clock import clock
from db import db, stamp_create


def post_invoice(subscription_id, source_kind, source_ref_id, amount_cents):
    """Post an immutable invoice. lifetime_billed_cents is derived as a running sum,
    so callers do not write it directly (PRD §3.14)."""
    rec = {
        "subscription_id": subscription_id,
        "source_kind": source_kind,       # CYCLE | SWAP | EARLY_CANCEL | RETURN_SETTLEMENT
        "source_ref_id": source_ref_id,   # polymorphic per source_kind
        "amount_cents": amount_cents,     # may be negative for a swap downgrade net credit
        "posted_at_iso": clock.now_iso(),
    }
    # Invoice carries only id + created_at (no updated_at / version) — PRD §2.4.
    stamp_create(rec, with_version=False)
    db.invoices[rec["id"]] = rec
    return rec


def unpaid_sum(subscription_id, source_kind):
    """Sum of a subscription's invoices for a given source_kind.

    PRD §3.11 waterfall draws on 'unpaid CYCLE' and 'unpaid EARLY_CANCEL' invoices.
    The system has no payment-reconciliation endpoint, so every posted CYCLE/
    EARLY_CANCEL invoice is treated as unpaid at settlement time.
    """
    return sum(
        inv["amount_cents"]
        for inv in db.invoices.values()
        if inv["subscription_id"] == subscription_id and inv["source_kind"] == source_kind
    )
