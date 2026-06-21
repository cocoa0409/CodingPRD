"""Revenue ledger and instructor balances (PRD §2.7, calc instructor_balances).

Balances are NEVER stored as running totals; they are always aggregated fresh
over the instructor's RevenueLedgerEntry rows. Every write/flip of a ledger row
recomputes the owning instructor's balances, which is itself a mutation of the
instructor (refresh updated_at, bump version).
"""
import clock
from db import db, new_id, iso
from services.common import stamp_create, touch


def write_entry(instructor_id, entry_type, amount_cents, status,
                enrollment_id=None, payout_id=None):
    """Append an immutable RevenueLedgerEntry (id + created_at only)."""
    rec = {
        "id": new_id(),
        "instructor_id": instructor_id,
        "enrollment_id": enrollment_id,
        "payout_id": payout_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "status": status,
        "created_at": iso(clock.now()),
    }
    rec["_seq"] = db.next_seq()
    db.ledger_entries[rec["id"]] = rec
    return rec


def _compute(instructor_id):
    entries = [e for e in db.ledger_entries.values()
               if e["instructor_id"] == instructor_id]
    pending = sum(e["amount_cents"] for e in entries
                  if e["entry_type"] == "SALE" and e["status"] == "PENDING")
    available = sum(e["amount_cents"] for e in entries
                    if e["entry_type"] == "SALE" and e["status"] == "AVAILABLE")
    payouts_taken = sum(-e["amount_cents"] for e in entries
                        if e["entry_type"] == "PAYOUT" and e["status"] == "PAID")
    payout_balance = max(available - payouts_taken, 0)
    lifetime = sum(e["amount_cents"] for e in entries
                   if e["entry_type"] in ("SALE", "REFUND")
                   and e["status"] != "CLAWED_BACK")
    return pending, payout_balance, lifetime


def recompute_balances(instructor_id):
    """Recompute and persist an instructor's three balance fields.

    Per PRD §2.7 a balance recompute is a mutation of the instructor only when a
    value actually moves (a reconciliation that *changes* a derived field). When
    the freshly computed balances equal the stored ones — e.g. a plain read with
    no intervening ledger change, or a payout request that writes no ledger row —
    nothing changed, so we do NOT bump updated_at/version. This keeps the
    instructor-version OCC coherent: reading the instructor does not desync the
    version a client carries into a payout approval.
    """
    inst = db.instructors.get(instructor_id)
    if inst is None:
        return None
    pending, payout_balance, lifetime = _compute(instructor_id)
    changed = (inst.get("pending_balance_cents") != pending
               or inst.get("payout_balance_cents") != payout_balance
               or inst.get("lifetime_earned_cents") != lifetime)
    inst["pending_balance_cents"] = pending
    inst["payout_balance_cents"] = payout_balance
    inst["lifetime_earned_cents"] = lifetime
    if changed:
        touch(inst)
    return inst
