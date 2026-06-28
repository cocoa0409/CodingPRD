"""Shared policy-mutation helpers used by several route blueprints."""
from db import db, new_common
from services.lookups import children_by_policy


def append_ledger(policy_id, entry_kind, amount_cents, memo=None):
    """Append an immutable PremiumLedgerEntry (id + created_at only)."""
    entry = new_common(versioned=False)
    entry.update({
        "policy_id": policy_id,
        "entry_kind": entry_kind,
        "amount_cents": amount_cents,
        "memo": memo,
        "_seq": db.next_seq(),
    })
    db.ledger_entries[entry["id"]] = entry
    return entry


def reconcile_premium(policy):
    """policy_premium_reconciliation (PRD §3.4): sum already-rounded line subtotals.

    base = sum of rated_premium_cents over Coverages in {SELECTED, ACTIVE}
    rider = sum of rider_premium_cents over Riders in {SELECTED, ACTIVE}
    total = base + rider
    """
    coverages = children_by_policy(db.coverages, policy["id"])
    riders = children_by_policy(db.riders, policy["id"])
    base = sum(c["rated_premium_cents"] for c in coverages if c["status"] in ("SELECTED", "ACTIVE"))
    rider = sum(r["rider_premium_cents"] for r in riders if r["status"] in ("SELECTED", "ACTIVE"))
    policy["base_premium_cents"] = base
    policy["rider_premium_cents"] = rider
    policy["total_premium_cents"] = base + rider
