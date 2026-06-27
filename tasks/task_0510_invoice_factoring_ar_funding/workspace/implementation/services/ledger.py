"""Denormalized balance recomputation + append-only ledger (§2.8)."""

import db
from common import stamp_audit
from services import calc


def recompute_client_balances(client):
    """Recompute reserve_balance_cents and funded_advance_outstanding_cents
    from the client's invoices in {FUNDED, OUTSTANDING, SHORT_PAID}."""
    reserve = 0
    funded = 0
    for inv in db.invoices.values():
        if inv["client_id"] == client["id"] and inv["status"] in calc.EXPOSURE_STATUSES:
            reserve += inv["reserve_held_cents"]
            funded += inv["advance_outstanding_cents"]
    client["reserve_balance_cents"] = reserve
    client["funded_advance_outstanding_cents"] = funded
    return client


def recompute_debtor_balance(debtor):
    """Recompute outstanding_face_cents from the debtor's invoices in the
    three exposure statuses."""
    face = 0
    for inv in db.invoices.values():
        if inv["debtor_id"] == debtor["id"] and inv["status"] in calc.EXPOSURE_STATUSES:
            face += inv["face_amount_cents"]
    debtor["outstanding_face_cents"] = face
    return debtor


def append_ledger(client, invoice_id, entry_type, amount_cents):
    """Append an immutable ledger entry, snapshotting the client's
    reserve_balance_cents *after* the entry. Client balances must already be
    recomputed before calling so the snapshot is correct."""
    entry = {
        "client_id": client["id"],
        "invoice_id": invoice_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "reserve_balance_after_cents": client["reserve_balance_cents"],
    }
    stamp_audit(entry)
    db.ledger_entries[entry["id"]] = entry
    return entry
