"""Shared cascade helpers — refund flips, prescription auto-archive, etc.

These are called from many state transitions, so we centralise them here.
"""

from __future__ import annotations

from db import (
    append_audit_log,
    db,
    emit_external_event,
    platform_clock,
    stamp_update,
)
from middleware import current_actor

# Order dispensing states that are "outstanding" / non-terminal w.r.t. prescription archive.
NON_TERMINAL_DISPENSING = {
    "PENDING_REVIEW",
    "PHARMACIST_REVIEWING",
    "APPROVED",
    "DISPENSED",
    "SHIPPED",
}


def refund_if_paid(platform: dict, order: dict) -> None:
    """If payment_status==PAID, flip to REFUNDED and emit refund audit + event.

    Used as a cascade target whenever an order's dispensing flips to
    REJECTED or CANCELLED while it was paid.
    """
    if order.get("payment_status") != "PAID":
        return
    order["payment_status"] = "REFUNDED"
    stamp_update(order, platform)
    actor_id, actor_role = current_actor()
    append_audit_log(
        platform=platform,
        subject_type="ORDER",
        subject_id=order["id"],
        action="ORDER_REFUNDED",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={
            "payment_status": order["payment_status"],
            "dispensing_status": order["dispensing_status"],
            "version": order["version"],
        },
    )
    emit_external_event(
        platform=platform,
        channel="PAYMENT",
        event_type="order.refunded",
        subject_type="ORDER",
        subject_id=order["id"],
        payload={"order_id": order["id"], "version": order["version"]},
        idempotency_key=f"order.refunded:{order['id']}:{order['version']}",
    )


def evaluate_prescription_archive(platform: dict, prescription_id: str | None) -> None:
    """Auto-archive an APPROVED prescription when no referencing Order remains
    in a non-terminal dispensing state.
    """
    if not prescription_id:
        return
    rx = db.prescriptions.get(prescription_id)
    if not rx or rx.get("platform_id") != platform["id"]:
        return
    if rx.get("status") != "APPROVED":
        return
    referencing = [
        o
        for o in db.orders.values()
        if o.get("platform_id") == platform["id"]
        and o.get("prescription_id") == prescription_id
    ]
    for o in referencing:
        if o.get("dispensing_status") in NON_TERMINAL_DISPENSING:
            return  # at least one outstanding referencing order — no archive yet
    # All referencing orders are terminal — archive the prescription.
    rx["status"] = "ARCHIVED"
    rx["archived_at"] = platform_clock(platform)
    stamp_update(rx, platform)
    emit_external_event(
        platform=platform,
        channel="E_PRESCRIPTION_PLATFORM",
        event_type="prescription.archived",
        subject_type="PRESCRIPTION",
        subject_id=rx["id"],
        payload={"prescription_id": rx["id"], "version": rx["version"]},
        idempotency_key=f"prescription.archived:{rx['id']}:{rx['version']}",
    )


def cascade_off_shelve_to_orders(platform: dict, drug_id: str) -> None:
    """When a drug goes OFF_SHELF, every Order containing the drug whose
    dispensing_status is PENDING_REVIEW or PHARMACIST_REVIEWING flips to
    REJECTED, with refund cascade if PAID.
    """
    affected_rxs: set[str] = set()
    for order in list(db.orders.values()):
        if order.get("platform_id") != platform["id"]:
            continue
        if order.get("dispensing_status") not in {"PENDING_REVIEW", "PHARMACIST_REVIEWING"}:
            continue
        contains = any(line["drug_id"] == drug_id for line in (order.get("items") or []))
        if not contains:
            continue
        order["dispensing_status"] = "REJECTED"
        stamp_update(order, platform)
        refund_if_paid(platform, order)
        if order.get("prescription_id"):
            affected_rxs.add(order["prescription_id"])
    for rx_id in affected_rxs:
        evaluate_prescription_archive(platform, rx_id)
