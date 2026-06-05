"""Tenant ledger: append-only LedgerEntry records + balance roll-up (PRD §3.9).

A LedgerEntry is append-only (id + created_at only). amount_cents is signed:
positive increases the tenant balance (charge), negative decreases it (payment/
credit). Lease.outstanding_balance_cents is the running sum of all entries for
the lease, recomputed on every posting.
"""
from __future__ import annotations

import db
from services.common import new_append_only_fields


def post_ledger_entry(lease: dict, entry_type: str, amount_cents: int,
                      source_reconciliation_id=None) -> dict:
    """Append a LedgerEntry and recompute the lease balance (caller bumps lease.version)."""
    entry = {
        **new_append_only_fields(),
        "lease_id": lease["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "source_reconciliation_id": source_reconciliation_id,
    }
    db.ledger_entries[entry["id"]] = entry
    recompute_balance(lease)
    return entry


def recompute_balance(lease: dict):
    """Lease.outstanding_balance_cents = running sum of every ledger entry's amount."""
    total = 0
    for e in db.ledger_entries.values():
        if e["lease_id"] == lease["id"]:
            total += e["amount_cents"]
    lease["outstanding_balance_cents"] = total
