"""Garnishment amount_collected_cents reconciliation across paycheck lifecycle."""
from __future__ import annotations

from ..clock import now_iso
from ..store import store


def recompute_amount_collected(order_id: str) -> None:
    """Recompute a garnishment order's amount_collected_cents:
    sum of allocations across this employee's APPROVED-or-PAID paychecks
    minus sum across this employee's VOIDED paychecks.
    Auto-transition ACTIVE↔SATISFIED as needed.
    """
    s = store()
    order = s.garnishment_orders.get(order_id)
    if order is None:
        return
    employee_id = order["employee_id"]
    collected = 0
    for pc in s.paychecks.values():
        if pc["employee_id"] != employee_id:
            continue
        allocations = pc.get("garnishment_allocations") or {}
        amt = allocations.get(order_id, 0)
        if amt <= 0:
            continue
        if pc["status"] in ("APPROVED", "PAID"):
            collected += amt
        elif pc["status"] == "VOIDED":
            collected -= amt
    collected = max(0, collected)

    prev_collected = order["amount_collected_cents"]
    prev_status = order["status"]
    order["amount_collected_cents"] = collected

    new_status = prev_status
    if prev_status == "ACTIVE" and collected >= order["total_owed_cents"]:
        new_status = "SATISFIED"
    elif prev_status == "SATISFIED" and collected < order["total_owed_cents"]:
        new_status = "ACTIVE"

    if new_status != prev_status or collected != prev_collected:
        order["status"] = new_status
        order["updated_at"] = now_iso()
        order["version"] = order["version"] + 1


def recompute_orders_affected_by_paycheck(paycheck_id: str) -> None:
    s = store()
    pc = s.paychecks.get(paycheck_id)
    if pc is None:
        return
    allocations = pc.get("garnishment_allocations") or {}
    for order_id in list(allocations.keys()):
        recompute_amount_collected(order_id)
