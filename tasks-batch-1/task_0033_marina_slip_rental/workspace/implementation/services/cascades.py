"""Cross-entity cascade helpers (scaffold §1.2 / PRD §3.8, §3.3).

These functions encapsulate the multi-row mutations that fan out from one
operation:

  * waitlist promotion fan-out on Slip OCCUPIED -> AVAILABLE (PRD §3.8)
  * liveaboard revocation fan-out on Tenant APPROVED -> REVOKED (PRD §3.3)

Every entity whose persisted state changes during the request has its
``version`` bumped by exactly 1 and its ``updated_at`` re-stamped (PRD §2.9).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import db


# ---- waitlist queue helpers -------------------------------------------------


def _queue_sort_key(entry: Dict) -> Tuple:
    """Strict ordering used for promotion + position computation.

    Per scaffold/PRD: order by requested_at ASC, tie-break created_at ASC.
    """
    return (entry.get("requested_at", ""), entry.get("created_at", ""))


def queued_entries_for(marina_id: str, slip_id: str) -> List[Dict]:
    """All QUEUED waitlist entries for (marina_id, target_slip_id), sorted."""
    items = [
        e
        for e in db.transfer_waitlist.values()
        if e.get("marina_id") == marina_id
        and e.get("target_slip_id") == slip_id
        and e.get("status") == "QUEUED"
    ]
    items.sort(key=_queue_sort_key)
    return items


def recompute_positions(marina_id: str, slip_id: str) -> None:
    """Recompute the 1-based ``position`` field for the (marina_id, slip_id)
    QUEUED queue.

    Position recomputation does NOT bump ``version`` on the recomputed entries;
    PRD §3.8 / §3.9 list "position recomputed" alongside the explicit version
    bumps for the transitioning entry only.
    """
    queued = queued_entries_for(marina_id, slip_id)
    for idx, entry in enumerate(queued, start=1):
        entry["position"] = idx


def promote_waitlist_head(slip: Dict) -> Optional[Dict]:
    """Implement calculations.waitlist_promotion_pick.

    If a head exists for (slip.marina_id, slip.id) in QUEUED, transition it
    to PROMOTED, set slip.status = RESERVED, and recompute remaining queue
    positions. Returns the promoted entry (already version-bumped) or None
    when no candidates exist.

    NOTE: The caller is responsible for bumping the SLIP's version (it does
    this exactly once for the OCCUPIED -> {AVAILABLE | RESERVED} transition,
    matching PRD §3.8's "the slip's version is bumped" statement.)
    """
    queued = queued_entries_for(slip["marina_id"], slip["id"])
    if not queued:
        slip["status"] = "AVAILABLE"
        return None
    head = queued[0]
    head["status"] = "PROMOTED"
    db.bump(head)
    slip["status"] = "RESERVED"
    # Position recompute for the now-shorter QUEUED list.
    recompute_positions(slip["marina_id"], slip["id"])
    return head


# ---- liveaboard revocation cascade ------------------------------------------


def cancel_reserved_liveaboard_leases(tenant_id: str) -> List[Dict]:
    """Cascade tenant liveaboard REVOKE -> cancel every RESERVED liveaboard
    lease for the tenant (PRD §3.3).

    Each cancelled lease's slip transitions RESERVED -> AVAILABLE (mirroring
    the lease-cancel transition in §1.2 Slip), each row mutated has its
    ``version`` bumped (PRD §2.9).

    Returns the list of cancelled leases for diagnostics; callers typically
    discard the return value.
    """
    cancelled: List[Dict] = []
    target = [
        lease
        for lease in db.leases.values()
        if lease.get("tenant_id") == tenant_id
        and lease.get("is_liveaboard") is True
        and lease.get("status") == "RESERVED"
    ]
    for lease in target:
        lease["status"] = "CANCELLED"
        db.bump(lease)
        cancelled.append(lease)
        # Cascade the parent slip RESERVED -> AVAILABLE; mirror the explicit
        # Slip RESERVED->AVAILABLE transition in scaffold §1.2 Slip.
        slip = db.slips.get(lease.get("slip_id"))
        if slip is not None and slip.get("status") == "RESERVED":
            slip["status"] = "AVAILABLE"
            db.bump(slip)
    return cancelled
