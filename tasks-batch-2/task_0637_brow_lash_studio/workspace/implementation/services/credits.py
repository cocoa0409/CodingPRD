"""Credit ledger + membership credit-balance reconciliation.

PRD §2.6, §3.4: credit_balance is always the sum of all delta values in the
ledger and is never negative. Ledger entries are append-only and immutable,
carry only id + created_at (no updated_at / version) (PRD §2.5).
"""
from datetime import datetime, timezone

from db import store


def _now_iso():
    dt = datetime.now(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (".%03dZ" % millis)


def append_ledger_entry(membership_id, delta, reason, source_ref_id):
    """Append a CreditLedgerEntry. Returns the new entry record.

    reason in {GRANT, ROLLOVER, ROLLOVER_FORFEIT, CONSUME, REFUND}.
    source_ref_id: appointment id for CONSUME/REFUND; membership id for
    GRANT/ROLLOVER/ROLLOVER_FORFEIT (PRD §3.4)."""
    entry = {
        "id": store.new_id(),
        "membership_id": membership_id,
        "delta": delta,
        "reason": reason,
        "source_ref_id": source_ref_id,
        "created_at": _now_iso(),
        "_seq": store.next_seq(),
    }
    store.credit_ledger_entries[entry["id"]] = entry
    return entry


def ledger_for_membership(membership_id):
    entries = [e for e in store.credit_ledger_entries.values()
               if e["membership_id"] == membership_id]
    return sorted(entries, key=lambda e: e["_seq"])


def credit_balance(membership_id):
    """credit_balance = sum of all CreditLedgerEntry.delta for this membership."""
    return sum(e["delta"] for e in store.credit_ledger_entries.values()
               if e["membership_id"] == membership_id)
