"""Credit ledger: projection (calc membership_credit_balance) + entry writes.

PRD 3.2: A membership's credit_balance is the sum of delta_credits across all
ledger entries for that membership_id, processed in created_at ascending order
(ties broken by created_at and then by write sequence, never by id).
"""
from db import db
from util import new_id
from clock import clock


def ledger_entries_for(membership_id):
    entries = [e for e in db.credit_ledger.values()
               if e["membership_id"] == membership_id]
    entries.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return entries


def membership_credit_balance(membership_id):
    return sum(e["delta_credits"] for e in ledger_entries_for(membership_id))


def write_ledger_entry(membership, entry_type, delta_credits, source_kind, source_ref_id):
    eid = new_id()
    entry = {
        "id": eid,
        "created_at": clock.get(),
        "_seq": db.next_seq(),
        "membership_id": membership["id"],
        "entry_type": entry_type,
        "delta_credits": delta_credits,
        "source_kind": source_kind,
        "source_ref_id": source_ref_id,
        "cycle_index": membership["cycle_index"],
    }
    db.credit_ledger[eid] = entry
    return entry
