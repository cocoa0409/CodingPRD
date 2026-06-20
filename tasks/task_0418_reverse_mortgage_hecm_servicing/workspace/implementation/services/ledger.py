"""Append-only ledger posting (§3.12). Entries are never edited."""
import db


def post_entry(loan, entry_type, amount_cents, source_ref_id=None):
    """Append a LedgerEntry. amount_cents is signed (positive = balance up).
    balance_after_cents captures loan.principal_balance_cents at post time.
    posted_month_index = loan.months_elapsed. Lean entity: id + created_at only."""
    entry = {
        "loan_id": loan["id"],
        "entry_type": entry_type,
        "source_ref_id": source_ref_id,
        "amount_cents": amount_cents,
        "balance_after_cents": loan["principal_balance_cents"],
        "posted_month_index": loan["months_elapsed"],
    }
    db.stamp_create(entry, with_version=False)
    db.ledger_entries[entry["id"]] = entry
    return entry
