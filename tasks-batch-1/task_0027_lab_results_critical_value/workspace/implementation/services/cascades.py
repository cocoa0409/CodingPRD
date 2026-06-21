"""Cascade engine: orchestrates the multi-hop state transitions described
in PRD §2.7 and §2.8.

Three primary cascades:
  (a) Specimen IN_TRANSIT->ACCESSIONED  →  LabOrder DRAFT->ACCESSIONED (recompute counters)
  (b) Specimen *->REJECTED               →  recompute counters; if specimens_count == 0
                                              AND order in ACCESSIONED -> CANCELLED;
                                              cascade CriticalNotification PENDING|SENT -> VOIDED
  (c) Result PROVISIONAL->RELEASED       →  bump LabOrder.version; first release ⇒
                                              LabOrder ACCESSIONED->RESULTED + pin TAT
"""
from __future__ import annotations

from typing import Dict, Any, List, Optional

import db
from services.calculations import (
    recompute_order_counters,
    recompute_patient_release_count,
    compute_tat_clinical,
)


def void_pending_or_sent_notifications_for_result(result_id: str) -> None:
    """VOID any CriticalNotification on the given Result currently in PENDING/SENT."""
    for n in db.critical_notifications.values():
        if n.get("result_id") != result_id:
            continue
        if n.get("status") in ("PENDING", "SENT"):
            n["status"] = "VOIDED"
            db.bump(n)


def void_pending_or_sent_notifications_for_order(order_id: str) -> None:
    """VOID notifications across all Results of an order."""
    result_ids = {r["id"] for r in db.results.values() if r.get("lab_order_id") == order_id}
    for n in db.critical_notifications.values():
        if n.get("result_id") not in result_ids:
            continue
        if n.get("status") in ("PENDING", "SENT"):
            n["status"] = "VOIDED"
            db.bump(n)


def cascade_specimen_to_lab_order(order: Dict[str, Any]) -> None:
    """After a specimen state change, run the order-level cascade.

    Called by accession (first ACCESSIONED → order goes DRAFT->ACCESSIONED) and
    by reject (specimens_count drops to 0 with order ACCESSIONED → order
    cascades to CANCELLED + notifications cascade to VOIDED).

    Counters MUST already be recomputed before invoking this.
    """
    if order.get("status") == "DRAFT":
        # If any specimen is now ACCESSIONED, lift order to ACCESSIONED.
        if any(
            s for s in db.specimens.values()
            if s.get("lab_order_id") == order["id"] and s.get("status") == "ACCESSIONED"
        ):
            order["status"] = "ACCESSIONED"
            db.bump(order)
    elif order.get("status") == "ACCESSIONED":
        # If specimens_count dropped to 0, cancel by system actor + cascade
        # notifications to VOIDED.
        if order.get("specimens_count", 0) == 0:
            order["status"] = "CANCELLED"
            db.bump(order)
            void_pending_or_sent_notifications_for_order(order["id"])


def cascade_result_release(order: Dict[str, Any], result: Dict[str, Any]) -> None:
    """Result PROVISIONAL->RELEASED cascade onto LabOrder.

    - On first release of the order, transition ACCESSIONED->RESULTED and pin
      LabOrder.turn_around_time_minutes per §1.3.
    - Always bump LabOrder.version + refresh updated_at (OCC parent bump).
    """
    if order.get("status") == "ACCESSIONED":
        # is this the first RELEASED on this order?
        released = [
            r for r in db.results.values()
            if r.get("lab_order_id") == order["id"] and r.get("status") == "RELEASED"
        ]
        if released:
            order["status"] = "RESULTED"
            order["turn_around_time_minutes"] = compute_tat_clinical(order)
    db.bump(order)
