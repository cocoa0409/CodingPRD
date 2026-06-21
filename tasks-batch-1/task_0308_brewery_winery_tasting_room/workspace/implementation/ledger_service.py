"""Append-only compliance ledger writer (PRD §3.12).

Ledger entries are minted only as side effects of operations; no one writes them
directly. Each entry is immutable (id + created_at only)."""
from db import db, ledger_event_fields


def append_ledger(winery_id, entry_type, subject_type, subject_id,
                  volume_gallons=0, excise_cents=0, note=""):
    e = ledger_event_fields()
    e.update({
        "winery_id": winery_id,
        "entry_type": entry_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "volume_gallons": volume_gallons,
        "excise_cents": excise_cents,
        "note": note,
    })
    db.ledger_entries[e["id"]] = e
    return e
