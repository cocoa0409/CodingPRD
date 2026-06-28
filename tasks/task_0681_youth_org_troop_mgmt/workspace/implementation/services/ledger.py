"""FundLedgerEntry creation (PRD §2.9).

FundLedgerEntry is an append-only, write-once record carrying ONLY id and
created_at (PRD §2.4) — no updated_at, no version.
"""
from datetime import datetime, timezone

from db import db
from util import new_id, iso_now


def post_ledger_entry(council_id, account, amount_cents, source_kind,
                      source_ref_id, troop_id=None):
    """Append an immutable FundLedgerEntry row and return it."""
    now = iso_now(datetime.now(timezone.utc))
    entry = {
        "id": new_id(),
        "created_at": now,
        "council_id": council_id,
        "troop_id": troop_id,
        "account": account,
        "amount_cents": amount_cents,
        "source_kind": source_kind,
        "source_ref_id": source_ref_id,
        "_seq": db.next_seq(),
    }
    db.fund_ledger_entries[entry["id"]] = entry
    return entry
