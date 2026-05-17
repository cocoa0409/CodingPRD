"""BillingLedgerEntry append + cascade helpers.

The ledger is append-only (PRD §2.4); each row carries only id + created_at,
NO updated_at, NO version.
"""
from ..store import get_store, new_id


def append_ledger_entry(authorization_id: str, entry_type: str, units_delta: int,
                        reason_code: str, *, now: str,
                        session_id: str = None, claim_id: str = None) -> dict:
    """Create a BillingLedgerEntry row. Returns the new entry."""
    store = get_store()
    entry = {
        "id": new_id(),
        "authorization_id": authorization_id,
        "session_id": session_id,
        "claim_id": claim_id,
        "entry_type": entry_type,
        "units_delta": units_delta,
        "reason_code": reason_code,
        "created_at": now,
    }
    store.ledger_entries[entry["id"]] = entry
    return entry
