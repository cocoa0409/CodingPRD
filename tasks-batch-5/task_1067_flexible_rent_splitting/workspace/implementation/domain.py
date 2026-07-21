"""Shared domain mutations: ledger, reminders, recompute."""
from core import db, base_append, base_full, clock_iso, touch


def append_ledger(cycle_id, entry_type, amount_cents, memo):
    rec = base_append()
    rec.update({
        "cycle_id": cycle_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "memo": memo,
    })
    db.ledger_entries[rec["id"]] = rec
    return rec


def emit_reminder(renter_id, cycle_id, kind):
    rec = base_append()
    rec.update({
        "renter_id": renter_id,
        "cycle_id": cycle_id,
        "kind": kind,
        "channel": "EMAIL",
        "sent_at": clock_iso(),
    })
    db.reminders[rec["id"]] = rec
    return rec


def cycle_installments(cycle_id):
    return [i for i in db.installments.values() if i["cycle_id"] == cycle_id]


def recompute_repaid(cycle):
    """repaid = sum(amount) of PAID/WAIVED installments; outstanding = portion - repaid."""
    repaid = sum(i["amount_cents"] for i in cycle_installments(cycle["id"])
                 if i["status"] in ("PAID", "WAIVED"))
    cycle["repaid_amount_cents"] = repaid
    cycle["outstanding_cents"] = cycle["portion_cents"] - repaid


def recompute_net_remitted(cycle):
    advances = sum(e["amount_cents"] for e in db.ledger_entries.values()
                   if e["cycle_id"] == cycle["id"] and e["entry_type"] == "REMITTANCE_ADVANCE")
    reversals = sum(e["amount_cents"] for e in db.ledger_entries.values()
                    if e["cycle_id"] == cycle["id"] and e["entry_type"] == "REVERSAL")
    # REVERSAL amounts are stored negative; invariant = advances - reversals-magnitude.
    cycle["net_remitted_cents"] = advances + reversals
