"""Funding-pool ledger operations and shared cross-aggregate effects.

Pool invariant (PRD 2.8): allocated == available + obligated + paid at all
times. available_cents is always derived, never stored.
"""
from datetime import timedelta

from db import STORE, new_id, now
from helpers import touch, stamp_new


def pool_available(pool):
    return pool["allocated_cents"] - pool["obligated_cents"] - pool["paid_cents"]


def advance_for_item(item_id):
    """At most one advance ever per practice item."""
    for a in STORE.advances.values():
        if a["practice_item_id"] == item_id:
            return a
    return None


def item_held_cents(item):
    """Obligation currently held in the pool for this item.

    Set to scheduled_amount_cents at creation; reduced by issued_cents at
    advance issuance (issuance moves obligated -> paid); zeroed when the
    obligation is released (disburse / cancel / expire / drop / completion).
    """
    return item.get("_held_cents", 0)


def release_item_obligation(item, pool):
    """Release the item's remaining pool obligation back to available."""
    held = item_held_cents(item)
    if held and pool is not None:
        pool["obligated_cents"] -= held
        touch(pool)
    item["_held_cents"] = 0
    return held


def force_advance_return_due(advance):
    """Force ISSUED/RETURN_DUE advance with money outstanding to RETURN_DUE,
    due date reset to the current clock (item expiry / termination / drop /
    disbursement residual)."""
    if advance is None:
        return
    if advance["status"] in ("ISSUED", "RETURN_DUE") and advance["outstanding_cents"] > 0:
        advance["status"] = "RETURN_DUE"
        advance["expenditure_due_date"] = now()
        touch(advance)


def cancel_item(item, pool, release=True):
    """CANCELLED via drop-practice approval or contract termination.
    Cancellation never mutates the payment dimension."""
    item["certification_status"] = "CANCELLED"
    touch(item)
    if release:
        release_item_obligation(item, pool)
    adv = advance_for_item(item["id"])
    if adv is not None and adv["outstanding_cents"] > 0:
        force_advance_return_due(adv)


def expire_item(item, pool, release=True):
    """EXPIRED via the deadline sweep. Releases obligation, forces advance."""
    item["certification_status"] = "EXPIRED"
    touch(item)
    if release:
        release_item_obligation(item, pool)
    adv = advance_for_item(item["id"])
    if adv is not None and adv["outstanding_cents"] > 0:
        force_advance_return_due(adv)


def create_demand(contract_id, amount_cents, maintenance_obligation_id=None,
                  advance_payment_id=None, payment_request_id=None):
    d = {
        "id": new_id(),
        "contract_id": contract_id,
        "maintenance_obligation_id": maintenance_obligation_id,
        "advance_payment_id": advance_payment_id,
        "payment_request_id": payment_request_id,
        "amount_cents": amount_cents,
        "due_date": now() + timedelta(days=30),
        "status": "DEMANDED",
    }
    stamp_new(d)
    STORE.demands[d["id"]] = d
    return d
