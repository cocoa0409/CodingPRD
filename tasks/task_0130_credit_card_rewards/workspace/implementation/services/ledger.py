"""Points-ledger primitives.

The PRD §2.7 mandates that `points_balance` is computed as the signed sum of
`delta_points` over the account's ledger entries. We materialise that sum here.

Every ledger row is append-only.
"""
from __future__ import annotations

from store import store
from utils import fmt_iso


def append_entry(
    account_id: str,
    entry_type: str,
    delta_points: int,
    source_entity_type: str,
    source_entity_id: str | None,
) -> dict:
    """Append a single PointsLedgerEntry. Returns the entry dict.

    Does NOT recompute the account's points_balance — call recompute_balance()
    after a logical batch of appends.
    """
    now = store.now()
    entry_id = store.new_id()
    iso = fmt_iso(now)
    entry = {
        "id": entry_id,
        "account_id": account_id,
        "entry_type": entry_type,
        "source_entity_type": source_entity_type,
        "source_entity_id": source_entity_id,
        "delta_points": int(delta_points),
        "occurred_at": iso,
        "created_at": iso,
        # Internal sort key to preserve insertion order when occurred_at ties.
        "_seq": store.next_ledger_seq(),
    }
    store.points_ledger[entry_id] = entry
    return entry


def recompute_balance(account: dict) -> int:
    """Recompute account['points_balance'] from ledger. Returns the new balance."""
    total = 0
    aid = account["id"]
    for e in store.points_ledger.values():
        if e["account_id"] == aid:
            total += int(e["delta_points"])
    account["points_balance"] = total
    return total


def list_entries_for_account(account_id: str) -> list[dict]:
    """All ledger entries belonging to an account, sorted by occurred_at ASC."""
    rows = [e for e in store.points_ledger.values() if e["account_id"] == account_id]
    rows.sort(key=lambda e: (e["occurred_at"], e["_seq"]))
    return rows
