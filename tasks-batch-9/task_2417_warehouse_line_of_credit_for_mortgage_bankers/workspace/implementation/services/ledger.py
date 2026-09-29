"""The append-only facility ledger (PRD 2.6)."""

from clock import clock
from db import base_row, db


def post_entry(facility_id, advance_id, entry_type, direction, amount_cents, memo):
    entry = base_row(with_version=False)
    entry.update({
        "facility_id": facility_id,
        "advance_id": advance_id,
        "entry_type": entry_type,
        "direction": direction,
        "amount_cents": amount_cents,
        "posted_at": clock.now(),
        "memo": memo,
    })
    db.ledger_entries[entry["id"]] = entry
    return entry
