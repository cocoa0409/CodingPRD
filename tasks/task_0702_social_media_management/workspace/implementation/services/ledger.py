"""Append-only ledger writer (PRD §3.7). Lightweight write-once records."""
import db


def append_ledger(client_id, entry_type, amount_cents, boost_campaign_id, cycle_index):
    entry = {
        "id": db.new_id(),
        "client_id": client_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "boost_campaign_id": boost_campaign_id,
        "cycle_index": cycle_index,
    }
    db.stamp_create(entry, full=False)
    db.ledger_entries[entry["id"]] = entry
    return entry
