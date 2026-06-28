"""Ledger + credit-line balance helpers (PRD §2.8, §3.4).

LedgerEntry is immutable: id + created_at only. amount_cents is a signed movement
(debit positive increases outstanding principal; credit negative reduces it).
balance_after_cents is the outstanding PRINCIPAL on the line immediately after
the entry — a running balance.
"""
import db
from common import stamp_create_ledger


def line_draws(line_id):
    """All draws on a line."""
    return [d for d in db.draws.values() if d["credit_line_id"] == line_id]


def outstanding_draws_fifo(line_id):
    """OUTSTANDING draws ordered FIFO: drawn_at ASC, then created_at ASC (never id).

    drawn_at and created_at are stamped from the same logical clock; the internal
    _seq is the deterministic creation-order tie-break.
    """
    outstanding = [d for d in db.draws.values()
                   if d["credit_line_id"] == line_id and d["status"] == "OUTSTANDING"]
    return sorted(outstanding, key=lambda d: (d["_drawn_at_dt"], d["_created_dt"], d["_seq"]))


def recompute_outstanding(line):
    """Recompute outstanding_principal/fee/available_credit from OUTSTANDING draws."""
    line_id = line["id"]
    principal = 0
    fee = 0
    for d in db.draws.values():
        if d["credit_line_id"] == line_id and d["status"] == "OUTSTANDING":
            principal += d["principal_cents"] - d["principal_repaid_cents"]
            fee += d["fee_cents"] - d["fee_repaid_cents"]
    line["outstanding_principal_cents"] = principal
    line["outstanding_fee_cents"] = fee
    line["available_credit_cents"] = max(0, line["credit_limit_cents"] - principal)


def current_principal_balance(line_id):
    """The latest running balance (balance_after_cents) on the line, or 0 if no entries."""
    entries = [e for e in db.ledger_entries.values() if e["credit_line_id"] == line_id]
    if not entries:
        return 0
    latest = max(entries, key=lambda e: e["_seq"])
    return latest["balance_after_cents"]


def append_entry(*, credit_line_id, entry_type, amount_cents, balance_after_cents,
                 draw_id=None, remittance_id=None):
    """Create an immutable ledger entry."""
    entry = {
        "credit_line_id": credit_line_id,
        "draw_id": draw_id,
        "remittance_id": remittance_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "balance_after_cents": balance_after_cents,
    }
    stamp_create_ledger(entry)
    db.ledger_entries[entry["id"]] = entry
    return entry
