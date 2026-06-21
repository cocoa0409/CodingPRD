"""Cross-platform purchase aggregation and registry state transitions
(scaffold §1.3 registry_purchase_aggregation, PRD §3.5)."""
from __future__ import annotations

from typing import List, Optional

import db


def _ordered_purchases(registry_item_id: str) -> List[dict]:
    """All purchases on this registry item, sorted by (occurred_at ASC,
    created_at ASC). id is NEVER the tie-breaker."""
    purchases = [p for p in db.purchases.values()
                 if p.get("registry_item_id") == registry_item_id]
    purchases.sort(key=lambda p: (p.get("occurred_at", ""), p.get("created_at", "")))
    return purchases


def classify_new_purchase(registry_item: dict, new_purchase: dict) -> None:
    """For a freshly created Purchase row, determine its status and
    dup_of_purchase_id by replaying the chronological list.

    Mutates new_purchase in place but does NOT bump its version field
    (the caller stamps_common already, and new rows start at version=1).
    """
    target = int(registry_item["target_quantity"])
    purchases = _ordered_purchases(registry_item["id"])
    # Ensure the new row is included in `purchases` (it should be, since it
    # was already inserted into db.purchases before this call).
    running_confirmed = 0
    canonical_id: Optional[str] = None  # the "earliest CONFIRMED that ate the last slot"

    for p in purchases:
        if p["id"] == new_purchase["id"]:
            # Tentative for the new row.
            tentative = running_confirmed + int(p["quantity"])
            if tentative <= target:
                p["status"] = "CONFIRMED"
                p["dup_of_purchase_id"] = None
                running_confirmed = tentative
            else:
                p["status"] = "PENDING_REVIEW"
                # canonical: earliest CONFIRMED whose cumulative running_confirmed
                # BEFORE it was <= target and AFTER it exceeded target.
                # Replay again JUST for the CONFIRMED purchases (existing) up to
                # the moment they'd push the running total over.  We compute
                # this by walking the same chronological list and tracking the
                # running total of CONFIRMED rows; the canonical is the first
                # CONFIRMED row p' such that (prefix_before_p' + p'.quantity
                # + new_purchase.quantity) > target.
                p["dup_of_purchase_id"] = _find_canonical(
                    purchases, new_purchase, target
                )
        else:
            # An existing row contributes if status == CONFIRMED.
            if p.get("status") == "CONFIRMED":
                running_confirmed += int(p["quantity"])

    # After classification, recompute aggregates on the registry item.
    _recompute_aggregates(registry_item)


def _find_canonical(ordered: List[dict], new_purchase: dict, target: int) -> Optional[str]:
    """Find the earliest CONFIRMED p' such that, when we include p' along
    with new_purchase, the running confirmed total exceeds target. Returns
    its id, or None if none."""
    # Walk the ordered list, accumulating CONFIRMED quantities. Skip the new
    # purchase itself. When we find a CONFIRMED p' such that the running
    # total BEFORE p' was <= target and AFTER p' would exceed target with
    # new_purchase's quantity added, that's the canonical.
    running = 0
    nq = int(new_purchase["quantity"])
    for p in ordered:
        if p["id"] == new_purchase["id"]:
            continue
        if p.get("status") != "CONFIRMED":
            continue
        before = running
        after = running + int(p["quantity"])
        # The canonical is the earliest p' such that running_before_p' + p'.q
        # was <= target (it confirmed) but adding the new row's quantity would
        # have tipped it over. Per the spec: "running_confirmed BEFORE p'
        # reached <= target and AFTER p' exceeded".  We re-read this as
        # locating the p' whose own confirmation "ate the last slot" — i.e.
        # the p' that took the running total from <= (target - nq) to
        # something strictly > (target - nq).
        threshold = target - nq
        if before <= threshold and after > threshold:
            return p["id"]
        running = after
    # Fallback: if no such row exists (e.g., the very first ingest already
    # exceeds target on its own), return None.
    return None


def _recompute_aggregates(registry_item: dict) -> None:
    """Recompute fulfilled_quantity, pending_quantity, status; bump version."""
    ri_id = registry_item["id"]
    fulfilled = 0
    pending = 0
    for p in db.purchases.values():
        if p.get("registry_item_id") != ri_id:
            continue
        if p.get("status") == "CONFIRMED":
            fulfilled += int(p["quantity"])
        elif p.get("status") == "PENDING_REVIEW":
            pending += int(p["quantity"])
    registry_item["fulfilled_quantity"] = fulfilled
    registry_item["pending_quantity"] = pending
    # status transitions (OPEN <-> FULFILLED). ARCHIVED is frozen.
    current = registry_item.get("status")
    if current not in ("OPEN", "FULFILLED"):
        # ARCHIVED is terminal; skip status flips.
        pass
    else:
        target = int(registry_item["target_quantity"])
        if fulfilled >= target:
            registry_item["status"] = "FULFILLED"
        else:
            registry_item["status"] = "OPEN"
    db.bump(registry_item)


def recompute_after_purchase_mutation(registry_item: dict) -> None:
    """Called after a Purchase status change (cancel/promote) to refresh
    parent RegistryItem aggregates AND bump its version."""
    _recompute_aggregates(registry_item)
