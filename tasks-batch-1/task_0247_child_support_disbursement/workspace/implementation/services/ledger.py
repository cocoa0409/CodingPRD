"""Append-only ledger engine and derived balance computation (PRD 2.4)."""

from db import store


# Ledger rows are immutable events: only id + created_at + the recorded fields.
def post_entry(support_order_id, entry_type, bucket, amount_cents, source_ref,
               disbursement_lifecycle=False):
    """Append an immutable LedgerEntry. effective_at = current logical clock.

    `disbursement_lifecycle` flags the DISBURSEMENT send row and its compensating
    ADJUSTMENT return row. Those two rows form a conserved pair that, per PRD 3.7,
    must leave the order's owed buckets (current_support_due / interest / arrears)
    UNAFFECTED by both the send and the return — disbursement sits downstream of
    collection. They are therefore excluded from owed-balance derivation. The flag
    is internal bookkeeping and is not part of the serialized LedgerEntry.
    """
    now = store.now_iso()
    entry = {
        "id": store.new_id(),
        "created_at": now,
        "support_order_id": support_order_id,
        "entry_type": entry_type,
        "bucket": bucket,
        "amount_cents": amount_cents,
        "source_ref": source_ref,
        "effective_at": now,
        "_disbursement_lifecycle": disbursement_lifecycle,
    }
    store.ledger_entries[entry["id"]] = entry
    return entry


def _entries_for(order_id):
    return [e for e in store.ledger_entries.values() if e["support_order_id"] == order_id]


def current_support_due_cents(order_id):
    """sum(CHARGE & ADJUSTMENT @ CURRENT_SUPPORT) - sum(PAYMENT @ CURRENT_SUPPORT), floored at 0.

    Disbursement-lifecycle rows (the DISBURSEMENT send row and its compensating
    ADJUSTMENT return row) are excluded so the owed bucket is unaffected by both
    the send and the return — disbursement is downstream of collection (PRD 3.7).
    """
    total = 0
    for e in _entries_for(order_id):
        if e["bucket"] != "CURRENT_SUPPORT":
            continue
        if e.get("_disbursement_lifecycle"):
            continue
        if e["entry_type"] in ("CHARGE", "ADJUSTMENT"):
            total += e["amount_cents"]
        elif e["entry_type"] == "PAYMENT":
            total -= e["amount_cents"]
    return max(0, total)


def arrears_principal_cents(order_id):
    """sum(CHARGE & ADJUSTMENT @ PRINCIPAL) - sum(PAYMENT @ PRINCIPAL), floored at 0."""
    total = 0
    for e in _entries_for(order_id):
        if e["bucket"] != "PRINCIPAL":
            continue
        if e["entry_type"] in ("CHARGE", "ADJUSTMENT"):
            total += e["amount_cents"]
        elif e["entry_type"] == "PAYMENT":
            total -= e["amount_cents"]
    return max(0, total)


def interest_balance_cents(order_id):
    """sum(INTEREST & ADJUSTMENT @ INTEREST) - sum(PAYMENT @ INTEREST), floored at 0."""
    total = 0
    for e in _entries_for(order_id):
        if e["bucket"] != "INTEREST":
            continue
        if e["entry_type"] in ("INTEREST", "ADJUSTMENT"):
            total += e["amount_cents"]
        elif e["entry_type"] == "PAYMENT":
            total -= e["amount_cents"]
    return max(0, total)


def net_disbursed_to_family_cents(order_id):
    """Conserved cash-out quantity for this order (PRD 3.7 / SCAFFOLD field 106).

    A send adds +family_amount; the compensating return subtracts it back to the
    pre-send value, so a SENT+RETURNED pair leaves this UNCHANGED (zero drift).
    Equivalently: each disbursement contributes +family_amount once sent, then
    -family_amount once returned. The live total is therefore the sum of
    family_amount over disbursements currently in SENT status (PENDING and the
    fully-conserved RETURNED both contribute net zero).
    """
    total = 0
    for d in store.disbursements.values():
        if d["support_order_id"] != order_id:
            continue
        if d["status"] == "SENT":
            total += d["family_amount_cents"]
    return total
