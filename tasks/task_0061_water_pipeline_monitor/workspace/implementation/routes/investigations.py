"""LeakInvestigation read + narrow + dispatch."""
from flask import Blueprint, g

from db import (
    alerts,
    dmas,
    investigations,
    lock,
    next_seq,
    public,
    stamp_create,
    stamp_update,
    work_orders,
)
from errors import err
from middleware import get_json_body, require_auth
from response import success
from services.common import (
    active_topology_id,
    find_segment_in_version,
    get_investigation,
    get_network,
)
from services.investigations import narrow_investigation
from services.work_orders import compute_priority


bp = Blueprint("investigations", __name__)


@bp.get("/networks/<network_id>/investigations/<investigation_id>")
@require_auth(roles={"ControlOperator", "MaintenanceSupervisor", "Auditor"})
def get_investigation_endpoint(network_id, investigation_id):
    inv = get_investigation(network_id, investigation_id)
    return success(public(inv))


@bp.post("/networks/<network_id>/investigations/<investigation_id>/narrow")
@require_auth(roles={"ControlOperator"})
def narrow_endpoint(network_id, investigation_id):
    n = get_network(network_id)
    inv = get_investigation(network_id, investigation_id)
    if inv.get("status") != "OPEN":
        raise err("ERR_INVALID_STATE", "investigation is not OPEN")
    dma = dmas.get(inv.get("dma_id") or "")
    if not dma:
        raise err("ERR_INVALID_STATE", "investigation has no associated DMA")
    if dma.get("status") == "FROZEN":
        raise err("ERR_DMA_FROZEN", "DMA is frozen")
    with lock():
        narrow_investigation(n, inv, dma)
        inv["status"] = "NARROWED"
        stamp_update(inv)
        return success(public(inv))


@bp.post("/networks/<network_id>/investigations/<investigation_id>/dispatch")
@require_auth(roles={"ControlOperator"})
def dispatch_endpoint(network_id, investigation_id):
    n = get_network(network_id)
    inv = get_investigation(network_id, investigation_id)
    if inv.get("status") != "NARROWED":
        raise err("ERR_INVALID_STATE", "investigation is not NARROWED")
    dma = dmas.get(inv.get("dma_id") or "")
    if not dma:
        raise err("ERR_INVALID_STATE", "investigation has no DMA")
    if dma.get("status") not in ("OPEN", "RESTRICTED"):
        raise err("ERR_DMA_FROZEN", "DMA must be OPEN or RESTRICTED for dispatch")
    if not inv.get("suspected_segment_codes"):
        raise err("ERR_INVALID_STATE", "suspected_segment_codes is empty")
    body = get_json_body()
    tech_id = body.get("assigned_technician_id")
    target_seg = body.get("target_segment_code")
    if not tech_id or not isinstance(tech_id, str):
        raise err("ERR_BAD_REQUEST", "assigned_technician_id is required")
    if not target_seg or not isinstance(target_seg, str):
        raise err("ERR_BAD_REQUEST", "target_segment_code is required")
    av = active_topology_id(n)
    if not find_segment_in_version(av, target_seg):
        raise err("ERR_WORK_ORDER_SEGMENT_MISSING", "target_segment_code not in active topology")
    with lock():
        inv["assigned_technician_id"] = tech_id
        inv["status"] = "DISPATCHED"
        stamp_update(inv)
        # Auto-create WorkOrder
        wo = {
            "network_id": network_id,
            "origin": "INVESTIGATION",
            "alert_id": inv.get("alert_id"),
            "investigation_id": inv["id"],
            "dma_id": inv.get("dma_id"),
            "target_segment_code": target_seg,
            "status": "NEW",
            "assigned_technician_id": None,
            "parts_required": [],
            "started_at": None,
            "completed_at": None,
            "verified_at": None,
            "verification_failure_count": 0,
            "repair_record": None,
        }
        stamp_create(wo)
        wo["priority"] = compute_priority(n, wo)
        work_orders[wo["id"]] = wo
        return success(public(inv))
