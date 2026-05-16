"""Parent ledger arithmetic and balance waterfall (SCAFFOLD §1.3 / PRD §3.6).

PaidLedgerEntry rows are ordered (occurred_at ASC, id ASC) and replayed:
  TOP_UP   → running += amount_cents
  CHARGE   → running -= amount_cents
  REFUND   → running += amount_cents

All amounts are positive integer cents; sign is encoded by `type`.
"""

from core.store import STORE, stamp_append_only, now_iso, gen_id
from services.relationships import ledger_entries_for_parent


def _sort_key(entry):
    # occurred_at ASC, then id ASC
    return (entry["occurred_at"], entry["id"])


def parent_balance(parent_account_id: str) -> int:
    """Replay all ledger entries for this account in occurred_at ASC then id ASC."""
    rows = sorted(ledger_entries_for_parent(parent_account_id), key=_sort_key)
    running = 0
    for e in rows:
        t = e["type"]
        if t == "TOP_UP":
            running += e["amount_cents"]
        elif t == "CHARGE":
            running -= e["amount_cents"]
        elif t == "REFUND":
            running += e["amount_cents"]
    return running


def simulate_charge_balance(parent_account_id: str, charge_amount_cents: int) -> int:
    """Return what the running balance would be after appending this CHARGE."""
    return parent_balance(parent_account_id) - charge_amount_cents


def append_ledger_entry(parent_account_id: str, type_: str,
                       amount_cents: int, serving_record_id):
    """Append a PaidLedgerEntry. Server-stamps occurred_at = clock.now."""
    entry = {
        "parent_account_id": parent_account_id,
        "type": type_,
        "amount_cents": amount_cents,
        "serving_record_id": serving_record_id,
        "occurred_at": now_iso(),
    }
    stamp_append_only(entry)
    STORE.ledger_entries[entry["id"]] = entry
    return entry


def find_charge_for_serving(parent_account_id: str, serving_record_id: str):
    """Return the CHARGE PaidLedgerEntry linked to this serving for this parent, or None."""
    for e in STORE.ledger_entries.values():
        if (e["parent_account_id"] == parent_account_id
                and e["type"] == "CHARGE"
                and e.get("serving_record_id") == serving_record_id):
            return e
    return None


def find_refund_for_serving(parent_account_id: str, serving_record_id: str):
    """Return the REFUND PaidLedgerEntry already linked to this serving, or None."""
    for e in STORE.ledger_entries.values():
        if (e["parent_account_id"] == parent_account_id
                and e["type"] == "REFUND"
                and e.get("serving_record_id") == serving_record_id):
            return e
    return None
