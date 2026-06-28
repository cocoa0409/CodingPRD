"""Cross-entity domain operations: mutation bookkeeping, escrow accounting,
ownership checks, temporal-overlap checks, and the two named cascades
(PRD §2.4, §2.5, §3.7).

Every server change to a resource refreshes its updated_at and increments its
version (PRD §2.4) — including derived-field recomputations cascading from
another entity's change. touch() is the single chokepoint that guarantees this.
"""

from flask import g

import errors
from db import db, now_ts


def touch(record):
    """Refresh updated_at and bump version on any mutation (PRD §2.4)."""
    record["updated_at"] = now_ts()
    record["version"] += 1


# ---------------------------------------------------------------------------
# Escrow ledger (PRD §3.7): pure integer aggregation, exact, no rounding.
# ---------------------------------------------------------------------------

def escrow_deposit_total(order_id):
    return sum(d["amount_cents"] for d in db.deposits.values()
               if d["order_id"] == order_id and d["status"] == "POSTED")


def escrow_disbursed_total(order_id):
    return sum(d["amount_cents"] for d in db.disbursements.values()
               if d["order_id"] == order_id and d["status"] == "WIRED")


def escrow_balance(order_id):
    return escrow_deposit_total(order_id) - escrow_disbursed_total(order_id)


# ---------------------------------------------------------------------------
# Agency ownership (PRD §2.1): an Agency may act only on its own orders, and the
# constraint propagates to every resource reachable through one of those orders.
# ---------------------------------------------------------------------------

def require_agency_owns_order(order):
    """If the caller is an Agency, enforce Order.agency_id == X-User-ID (403)."""
    if g.user_role == "Agency" and order["agency_id"] != g.user_id:
        raise errors.unauthorized("Agency may act only on its own orders")


# ---------------------------------------------------------------------------
# Commitment open-exception count (PRD §3.4): RAISED or CURATIVE_PENDING children.
# ---------------------------------------------------------------------------

def commitment_open_exception_count(commitment_id):
    return sum(1 for e in db.exceptions.values()
               if e["commitment_id"] == commitment_id
               and e["status"] in ("RAISED", "CURATIVE_PENDING"))


def order_current_issued_commitment(order_id):
    """Return the order's single ISSUED commitment, or None."""
    for c in db.commitments.values():
        if c["order_id"] == order_id and c["status"] == "ISSUED":
            return c
    return None


# ---------------------------------------------------------------------------
# Cascade A (PRD §2.5): fired when an Order is cancelled. Three linked steps plus
# the per-commitment exception void.
# ---------------------------------------------------------------------------

def cascade_a_void_policy(policy):
    """CASCADE A link 3: voiding a policy reverses its remittance (PENDING/REMITTED
    -> REVERSED) and removes its endorsements (REQUESTED/ATTACHED -> REMOVED)."""
    for r in db.remittances.values():
        if r["policy_id"] == policy["id"] and r["status"] in ("PENDING", "REMITTED"):
            r["status"] = "REVERSED"
            touch(r)
    for e in db.endorsements.values():
        if e["policy_id"] == policy["id"] and e["status"] in ("REQUESTED", "ATTACHED"):
            e["status"] = "REMOVED"
            touch(e)


def cascade_a_cancel_commitment(commitment):
    """CASCADE A link 1 (per commitment): commitment -> CANCELLED, which drives its
    PENDING/ISSUED policies to VOID (link 2 -> link 3) and voids its open
    exceptions."""
    commitment["status"] = "CANCELLED"
    touch(commitment)
    # link 2: every Policy of this commitment in {PENDING, ISSUED} -> VOID
    for p in db.policies.values():
        if p["commitment_id"] == commitment["id"] and p["status"] in ("PENDING", "ISSUED"):
            p["status"] = "VOID"
            touch(p)
            cascade_a_void_policy(p)
    # void this commitment's open exceptions
    for e in db.exceptions.values():
        if e["commitment_id"] == commitment["id"] and e["status"] in ("RAISED", "CURATIVE_PENDING"):
            e["status"] = "VOID"
            touch(e)


def cascade_a_cancel_order(order):
    """CASCADE A (PRD §2.5): every Commitment of the order in {ISSUED, UPDATED,
    DRAFT} -> CANCELLED, each unwinding its policies/remittances/endorsements and
    voiding its exceptions."""
    for c in db.commitments.values():
        if c["order_id"] == order["id"] and c["status"] in ("ISSUED", "UPDATED", "DRAFT"):
            cascade_a_cancel_commitment(c)


# ---------------------------------------------------------------------------
# Commitment EXPIRED cascade (PRD §3.4): void RAISED/CURATIVE_PENDING exceptions.
# ---------------------------------------------------------------------------

def void_commitment_open_exceptions(commitment):
    for e in db.exceptions.values():
        if e["commitment_id"] == commitment["id"] and e["status"] in ("RAISED", "CURATIVE_PENDING"):
            e["status"] = "VOID"
            touch(e)
