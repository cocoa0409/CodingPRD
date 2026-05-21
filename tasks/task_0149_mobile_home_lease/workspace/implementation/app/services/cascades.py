"""State transition cascade helpers shared across multiple routes."""
from __future__ import annotations

from typing import Any

from ..clock import clock
from ..store import store
from .calculations import recompute_outstanding_balance
from .entities import touch


def void_pending_notices_for_lease(lease_id: str) -> None:
    """Transition any DRAFT/ISSUED RentIncreaseNotice on this lease to VOIDED."""
    for notice in store.rent_notices.values():
        if notice.get("lease_id") != lease_id:
            continue
        if notice.get("status") in ("DRAFT", "ISSUED"):
            notice["status"] = "VOIDED"
            touch(notice)


def lease_grace_to_terminated(lease: dict[str, Any]) -> None:
    """Cascade Lease GRACE→TERMINATED (also serves CURRENT/DELINQUENT→TERMINATED via direct
    paths used by ILLEGAL_USE finalization).

    Side effects:
      - Lot.current_lease_id := null
      - Void any DRAFT/ISSUED RentIncreaseNotice on this lease
      - Resident.violation_count_12mo incremented by 1 (system-recomputed)
      - Lease.status := TERMINATED
    """
    lease["status"] = "TERMINATED"
    touch(lease)
    # Lot cleanup
    lot = store.lots.get(lease.get("lot_id", ""))
    if lot is not None and lot.get("current_lease_id") == lease["id"]:
        lot["current_lease_id"] = None
        touch(lot)
    void_pending_notices_for_lease(lease["id"])
    # Recompute resident violation count (will reflect the new FINALIZED_FOR_CAUSE)
    resident = store.residents.get(lease.get("resident_id", ""))
    if resident is not None:
        # Per scaffold: resident.violation_count_12mo incremented by 1 (and recomputed at boundaries)
        # We trust the rolling-count recompute that runs after the eviction case mutates.
        from .calculations import recompute_violation_count_12mo
        recompute_violation_count_12mo(resident)
        touch(resident)


def lease_back_from_grace(lease: dict[str, Any]) -> None:
    """When an eviction case exits IN_CURE via CURED or DISMISSED, the lease
    transitions GRACE → CURRENT (if balance 0) or GRACE → DELINQUENT (if balance > 0).
    """
    if lease.get("status") != "GRACE":
        return
    bal = recompute_outstanding_balance(lease)
    lease["status"] = "CURRENT" if bal == 0 else "DELINQUENT"
    touch(lease)


def lease_to_grace_from_eviction(lease: dict[str, Any]) -> None:
    """Lease CURRENT/DELINQUENT → GRACE when an eviction case enters IN_CURE."""
    if lease.get("status") in ("CURRENT", "DELINQUENT"):
        lease["status"] = "GRACE"
        touch(lease)


__all__ = [
    "void_pending_notices_for_lease",
    "lease_grace_to_terminated",
    "lease_back_from_grace",
    "lease_to_grace_from_eviction",
]
