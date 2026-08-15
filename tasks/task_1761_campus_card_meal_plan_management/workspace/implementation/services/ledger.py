"""Ledger posting and balance derivation (PRD 2.7, ledger_balance_recompute)."""

from db import store
from services.core import new_row, touch

CREDIT_TYPES = {
    "FUND", "ALLOCATION_GRANT", "PRORATION_CREDIT", "PROVISIONAL_CREDIT",
    "ADJUSTMENT_CREDIT", "PURCHASE_REVERSAL",
}
DEBIT_TYPES = {
    "PURCHASE", "FEE", "PRORATION_DEBIT", "ADJUSTMENT_DEBIT",
    "PROVISIONAL_CLAWBACK", "REFUND_PAYOUT", "FORFEIT",
}

ALL_ENTRY_TYPES = CREDIT_TYPES | DEBIT_TYPES


def post_entry(account, entry_type, amount_cents, description,
               reference_transaction_id=None, reference_dispute_id=None):
    """Append a LedgerEntry and recompute the account's derived balance.
    amount_cents is an unsigned magnitude strictly greater than zero."""
    assert entry_type in ALL_ENTRY_TYPES
    assert isinstance(amount_cents, int) and amount_cents > 0
    seq = 1 + max(
        (e["entry_sequence"] for e in store.ledger_entries.values()
         if e["account_id"] == account["id"]),
        default=0,
    )
    signed = amount_cents if entry_type in CREDIT_TYPES else -amount_cents
    account["balance_cents"] += signed
    entry = new_row(immutable=True)
    entry.update({
        "account_id": account["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "description": description,
        "reference_transaction_id": reference_transaction_id,
        "reference_dispute_id": reference_dispute_id,
        "entry_sequence": seq,
        "running_balance_cents": account["balance_cents"],
    })
    store.ledger_entries[entry["id"]] = entry
    touch(account)
    return entry


def entries_of_account(account_id):
    rows = [e for e in store.ledger_entries.values() if e["account_id"] == account_id]
    return sorted(rows, key=lambda e: (e["created_at"], e["entry_sequence"]))
