"""DMA posture recomputation and cascades (PRD §2.8, §3.3)."""
from db import alerts, dmas, stamp_update, work_orders
from services.audit import write_audit


CRITICAL_CONTRIB_STATUSES = {"OPEN", "ACKNOWLEDGED", "INVESTIGATING"}


def _count_open_critical(dma_id: str) -> int:
    return sum(
        1
        for a in alerts.values()
        if a.get("dma_id") == dma_id
        and a.get("severity") == "CRITICAL"
        and a.get("status") in CRITICAL_CONTRIB_STATUSES
    )


def _posture_from_count(count: int, prev_status: str) -> str:
    """Compute the new posture from the count, given the previous status.

    Per PRD §2.8: count==0 -> OPEN, 1<=count<3 -> RESTRICTED, count>=3 -> FROZEN.
    """
    if count == 0:
        return "OPEN"
    if count < 3:
        return "RESTRICTED"
    return "FROZEN"


def recompute_dma_posture(
    dma_id: str,
    *,
    network_id: str,
    actor_role: str = "system",
    actor_id: str = "system",
) -> dict:
    dma = dmas.get(dma_id)
    if not dma:
        return None
    old_status = dma.get("status", "OPEN")
    count = _count_open_critical(dma_id)
    new_status = _posture_from_count(count, old_status)
    dma["open_critical_alert_count"] = count
    if new_status != old_status:
        dma["status"] = new_status
        stamp_update(dma)
        # Side-effects per §1.2 DMA state machine + §2.8 PRD
        # FROZEN entry: pause IN_PROGRESS WorkOrders to AWAITING_VERIFICATION.
        if new_status == "FROZEN":
            for wo in work_orders.values():
                if (
                    wo.get("dma_id") == dma_id
                    and wo.get("status") == "IN_PROGRESS"
                ):
                    wo["status"] = "AWAITING_VERIFICATION"
                    wo["completed_at"] = wo.get("completed_at")  # don't overwrite
                    stamp_update(wo)
        # Audit log only on the two cross-freeze transitions.
        cross_freeze_edges = {
            ("RESTRICTED", "FROZEN"),
            ("RESTRICTED", "OPEN"),
        }
        if (old_status, new_status) in cross_freeze_edges:
            write_audit(
                network_id=network_id,
                actor_role=actor_role,
                actor_id=actor_id,
                action="DMA_POSTURE_CHANGED",
                resource_kind="DMA",
                resource_id=dma_id,
                detail={"from": old_status, "to": new_status},
            )
    return dma


def assert_not_frozen(dma_id: str) -> None:
    """Raise ERR_DMA_FROZEN if the DMA is currently FROZEN."""
    from errors import err
    if not dma_id:
        return
    dma = dmas.get(dma_id)
    if dma and dma.get("status") == "FROZEN":
        raise err("ERR_DMA_FROZEN", f"DMA {dma_id} is frozen")
