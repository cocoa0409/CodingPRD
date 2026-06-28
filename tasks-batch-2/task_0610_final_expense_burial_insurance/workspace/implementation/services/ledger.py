"""Append-only ledger (PRD §2.5)."""
import db
from clock import get_now, format_iso_millis


def append(policy_id, entry_type, amount_cents, balance_after_cents):
    """Append a LedgerEntry. Lightweight resource: id + created_at only."""
    entry = {
        "policy_id": policy_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "balance_after_cents": balance_after_cents,
        "occurred_at": format_iso_millis(get_now()),
    }
    db.stamp_light(entry)
    db.ledger_entries[entry["id"]] = entry
    return entry
