"""WorkOrder endpoints (create, assign, request-parts, start, complete, verify, cancel, list)."""
from flask import Blueprint, g, request

from clock import iso, iso_to_epoch_ms, server_now
from db import (
    alerts,
    devices,
    dmas,
    investigations,
    lock,
    pipeline_nodes,
    public,
    readings,
    stamp_create,
    stamp_update,
    work_orders,
)
from errors import err
from middleware import get_json_body, get_pagination, require_auth
from response import success, success_list
from services.audit import write_audit
from services.common import (
    active_topology_id,
    find_node_in_version,
    find_segment_in_version,
    get_network,
    get_work_order,
)
from services.dma_posture import recompute_dma_posture
from services.sync import emit_sync_for_work_order_closed
from services.work_orders import compute_priority


bp = Blueprint("work_orders", __name__)


VALID_ORIGINS = {"ALERT_AUTO", "INVESTIGATION", "INSPECTION_FINDING"}
LEAK_CLASS_CONFIRMING = {"LEAK_CONFIRMED", "JOINT_FAILURE", "PIPE_BURST"}


def _resolve_dma_for_workorder(network, origin, alert_id, investigation_id, target_segment_code):
    """Resolve a DMA id from alert/investigation/segment per the PRD §3.8."""
    if origin == "ALERT_AUTO" and alert_id:
        a = alerts.get(alert_id)
        if a:
            return a.get("dma_id")
    if origin == "INVESTIGATION" and investigation_id:
        inv = investigations.get(investigation_id)
        if inv:
            return inv.get("dma_id")
    # Try via target segment in active topology
    av = active_topology_id(network)
    seg = find_segment_in_version(av, target_segment_code)
    if seg:
        return seg.get("dma_id")
    return None


@bp.post("/networks/<network_id>/work-orders")
@require_auth(roles={"MaintenanceSupervisor"})
def create_work_order(network_id):
    n = get_network(network_id)
    body = get_json_body()
    origin = body.get("origin")
    if origin not in VALID_ORIGINS:
        raise err("ERR_BAD_REQUEST", "origin invalid")
    alert_id = body.get("alert_id")
    investigation_id = body.get("investigation_id")
    target_seg = body.get("target_segment_code")
    if not target_seg or not isinstance(target_seg, str):
        raise err("ERR_BAD_REQUEST", "target_segment_code is required")
    if origin == "ALERT_AUTO" and not alert_id:
        raise err("ERR_BAD_REQUEST", "alert_id is required when origin=ALERT_AUTO")
    if origin == "INVESTIGATION" and not investigation_id:
        raise err("ERR_BAD_REQUEST", "investigation_id is required when origin=INVESTIGATION")
    if alert_id and alert_id not in alerts:
        raise err("ERR_BAD_REQUEST", "alert_id does not exist")
    if investigation_id and investigation_id not in investigations:
        raise err("ERR_BAD_REQUEST", "investigation_id does not exist")
    av = active_topology_id(n)
    if not find_segment_in_version(av, target_seg):
        raise err("ERR_WORK_ORDER_SEGMENT_MISSING", "target_segment_code missing in active topology")
    dma_id = _resolve_dma_for_workorder(n, origin, alert_id, investigation_id, target_seg)
    # FROZEN check on the dma
    if dma_id:
        d = dmas.get(dma_id)
        if d and d.get("status") == "FROZEN":
            raise err("ERR_DMA_FROZEN", "DMA is frozen")
    parts_required = body.get("parts_required") or []
    if not isinstance(parts_required, list):
        raise err("ERR_BAD_REQUEST", "parts_required must be an array")
    with lock():
        wo = {
            "network_id": network_id,
            "origin": origin,
            "alert_id": alert_id,
            "investigation_id": investigation_id,
            "dma_id": dma_id,
            "target_segment_code": target_seg,
            "status": "NEW",
            "assigned_technician_id": None,
            "parts_required": list(parts_required),
            "started_at": None,
            "completed_at": None,
            "verified_at": None,
            "verification_failure_count": 0,
            "repair_record": None,
        }
        stamp_create(wo)
        wo["priority"] = compute_priority(n, wo)
        work_orders[wo["id"]] = wo
        return success(public(wo), 201)


@bp.get("/networks/<network_id>/work-orders/<work_order_id>")
@require_auth(roles={"MaintenanceSupervisor", "Technician", "ControlOperator", "Auditor"})
def get_work_order_endpoint(network_id, work_order_id):
    wo = get_work_order(network_id, work_order_id)
    return success(public(wo))


@bp.get("/networks/<network_id>/work-orders")
@require_auth(roles={"MaintenanceSupervisor", "Technician", "ControlOperator", "Auditor"})
def list_work_orders(network_id):
    get_network(network_id)
    status_f = request.args.get("status")
    priority_f = request.args.get("priority")
    tech_f = request.args.get("assigned_technician_id")
    dma_f = request.args.get("dma_id")
    limit, offset = get_pagination()
    rows = [
        wo for wo in work_orders.values()
        if wo.get("network_id") == network_id
        and (status_f is None or wo.get("status") == status_f)
        and (priority_f is None or wo.get("priority") == priority_f)
        and (tech_f is None or wo.get("assigned_technician_id") == tech_f)
        and (dma_f is None or wo.get("dma_id") == dma_f)
    ]
    rows.sort(key=lambda r: r.get("created_at") or "")
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/networks/<network_id>/work-orders/<work_order_id>/assign")
@require_auth(roles={"MaintenanceSupervisor"})
def assign_work_order(network_id, work_order_id):
    n = get_network(network_id)
    wo = get_work_order(network_id, work_order_id)
    if wo.get("status") != "NEW":
        raise err("ERR_INVALID_STATE", "work order is not NEW")
    dma = dmas.get(wo.get("dma_id") or "")
    if dma:
        if dma.get("status") == "FROZEN":
            raise err("ERR_DMA_FROZEN", "DMA is frozen")
        if dma.get("status") != "OPEN":
            raise err("ERR_INVALID_STATE", "DMA must be OPEN for assignment")
    av = active_topology_id(n)
    if not find_segment_in_version(av, wo.get("target_segment_code") or ""):
        raise err("ERR_WORK_ORDER_SEGMENT_MISSING", "target segment missing in active topology")
    body = get_json_body()
    tech_id = body.get("assigned_technician_id")
    if not tech_id or not isinstance(tech_id, str):
        raise err("ERR_BAD_REQUEST", "assigned_technician_id is required")
    with lock():
        wo["assigned_technician_id"] = tech_id
        wo["status"] = "ASSIGNED"
        stamp_update(wo)
        write_audit(
            network_id=network_id,
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="WORK_ORDER_ASSIGNED",
            resource_kind="WorkOrder",
            resource_id=work_order_id,
            detail={"assigned_technician_id": tech_id},
        ) if False else None  # AUDIT not enumerated for assignment; skip.
    return success(public(wo))


@bp.post("/networks/<network_id>/work-orders/<work_order_id>/request-parts")
@require_auth(roles={"Technician"})
def request_parts(network_id, work_order_id):
    wo = get_work_order(network_id, work_order_id)
    if wo.get("status") != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "work order is not ASSIGNED")
    if g.user_id != wo.get("assigned_technician_id"):
        raise err("ERR_FORBIDDEN", "not the assigned technician")
    dma = dmas.get(wo.get("dma_id") or "")
    if dma and dma.get("status") == "FROZEN":
        raise err("ERR_DMA_FROZEN", "DMA is frozen")
    body = get_json_body()
    parts = body.get("parts_required")
    if not isinstance(parts, list) or len(parts) == 0:
        raise err("ERR_BAD_REQUEST", "parts_required must be a non-empty array")
    with lock():
        wo["parts_required"] = parts
        wo["status"] = "PARTS_PENDING"
        stamp_update(wo)
    return success(public(wo))


@bp.post("/networks/<network_id>/work-orders/<work_order_id>/start")
@require_auth(roles={"Technician"})
def start_work_order(network_id, work_order_id):
    n = get_network(network_id)
    wo = get_work_order(network_id, work_order_id)
    cur = wo.get("status")
    if cur not in ("ASSIGNED", "PARTS_PENDING"):
        raise err("ERR_INVALID_STATE", "cannot start from this state")
    if g.user_id != wo.get("assigned_technician_id"):
        raise err("ERR_FORBIDDEN", "not the assigned technician")
    dma = dmas.get(wo.get("dma_id") or "")
    if dma and dma.get("status") == "FROZEN":
        raise err("ERR_DMA_FROZEN", "DMA is frozen")
    if cur == "ASSIGNED":
        parts = wo.get("parts_required") or []
        if parts:
            raise err("ERR_INVALID_STATE", "must request parts first")
    with lock():
        wo["status"] = "IN_PROGRESS"
        # Use the network's logical clock for started_at
        from clock import epoch_ms_to_iso
        wo["started_at"] = epoch_ms_to_iso(int(n.get("clock_epoch_ms", 0)))
        stamp_update(wo)
    return success(public(wo))


@bp.post("/networks/<network_id>/work-orders/<work_order_id>/complete")
@require_auth(roles={"Technician"})
def complete_work_order(network_id, work_order_id):
    n = get_network(network_id)
    wo = get_work_order(network_id, work_order_id)
    if wo.get("status") != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "work order is not IN_PROGRESS")
    if g.user_id != wo.get("assigned_technician_id"):
        raise err("ERR_FORBIDDEN", "not the assigned technician")
    body = get_json_body()
    rec = body.get("repair_record")
    if not isinstance(rec, dict):
        raise err("ERR_BAD_REQUEST", "repair_record is required")
    if not rec.get("leak_class"):
        raise err("ERR_BAD_REQUEST", "repair_record.leak_class is required")
    with lock():
        wo["repair_record"] = rec
        wo["status"] = "AWAITING_VERIFICATION"
        from clock import epoch_ms_to_iso
        wo["completed_at"] = epoch_ms_to_iso(int(n.get("clock_epoch_ms", 0)))
        stamp_update(wo)
    return success(public(wo))


def _has_post_repair_reading(network_id: str, wo: dict) -> bool:
    """Check at least one ACCEPTED reading after completed_at on devices mounted on the repaired segment."""
    completed_at = wo.get("completed_at")
    if not completed_at:
        return False
    completed_ms = iso_to_epoch_ms(completed_at)
    target_seg = wo.get("target_segment_code")
    # Resolve the segment in active topology to find its endpoint nodes
    n = None
    from db import networks
    n = networks.get(network_id)
    av = active_topology_id(n) if n else None
    seg = find_segment_in_version(av, target_seg) if av else None
    if not seg:
        return False
    endpoint_codes = {seg["from_node_code"], seg["to_node_code"]}
    relevant_devices = set()
    for d in devices.values():
        if d.get("network_id") != network_id:
            continue
        if d.get("mounted_on_node_code") in endpoint_codes:
            relevant_devices.add(d["id"])
    for r in readings.values():
        if r.get("device_id") not in relevant_devices:
            continue
        if r.get("validity") != "ACCEPTED":
            continue
        ing_ms = iso_to_epoch_ms(r["ingested_at"])
        if ing_ms > completed_ms:
            return True
    return False


@bp.post("/networks/<network_id>/work-orders/<work_order_id>/verify")
@require_auth(roles={"MaintenanceSupervisor"})
def verify_work_order(network_id, work_order_id):
    n = get_network(network_id)
    wo = get_work_order(network_id, work_order_id)
    if wo.get("status") != "AWAITING_VERIFICATION":
        raise err("ERR_INVALID_STATE", "work order is not AWAITING_VERIFICATION")
    # SoD: verifier must not be the assigned technician
    if g.user_id == wo.get("assigned_technician_id"):
        raise err("ERR_SEGREGATION_OF_DUTIES", "verifier must differ from technician")
    body = get_json_body()
    outcome = body.get("outcome")
    if outcome not in ("PASS", "FAIL"):
        raise err("ERR_BAD_REQUEST", "outcome must be PASS or FAIL")
    note = body.get("verification_note")

    if outcome == "PASS":
        if not _has_post_repair_reading(network_id, wo):
            raise err("ERR_INVALID_STATE", "no post-repair reading on repaired segment")
    with lock():
        if outcome == "PASS":
            wo["status"] = "CLOSED_VERIFIED"
            from clock import epoch_ms_to_iso
            wo["verified_at"] = epoch_ms_to_iso(int(n.get("clock_epoch_ms", 0)))
            stamp_update(wo)
            write_audit(
                network_id=network_id,
                actor_role=g.user_role,
                actor_id=g.user_id,
                action="WORK_ORDER_VERIFIED",
                resource_kind="WorkOrder",
                resource_id=work_order_id,
                detail={"outcome": "PASS", "note": note},
            )
            emit_sync_for_work_order_closed(wo)
            # Advance parent investigation if origin=INVESTIGATION
            if wo.get("origin") == "INVESTIGATION":
                inv = investigations.get(wo.get("investigation_id") or "")
                if inv and inv.get("status") == "DISPATCHED":
                    leak_class = (wo.get("repair_record") or {}).get("leak_class")
                    if leak_class in LEAK_CLASS_CONFIRMING:
                        inv["status"] = "CONFIRMED_LEAK"
                    elif leak_class == "NO_LEAK_FOUND":
                        inv["status"] = "FALSE_POSITIVE"
                    stamp_update(inv)
        else:
            # FAIL handling
            cur_fail = int(wo.get("verification_failure_count", 0))
            if cur_fail < 1:
                wo["verification_failure_count"] = cur_fail + 1
                wo["status"] = "IN_PROGRESS"
                stamp_update(wo)
            else:
                wo["verification_failure_count"] = cur_fail + 1
                wo["status"] = "CLOSED_REJECTED"
                stamp_update(wo)
                write_audit(
                    network_id=network_id,
                    actor_role=g.user_role,
                    actor_id=g.user_id,
                    action="WORK_ORDER_VERIFIED",
                    resource_kind="WorkOrder",
                    resource_id=work_order_id,
                    detail={"outcome": "FAIL", "final": True, "note": note},
                )
    return success(public(wo))


@bp.post("/networks/<network_id>/work-orders/<work_order_id>/cancel")
@require_auth(roles={"MaintenanceSupervisor"})
def cancel_work_order(network_id, work_order_id):
    wo = get_work_order(network_id, work_order_id)
    if wo.get("status") not in ("NEW", "ASSIGNED", "PARTS_PENDING"):
        raise err("ERR_INVALID_STATE", "work order cannot be cancelled from this state")
    dma = dmas.get(wo.get("dma_id") or "")
    if dma and dma.get("status") == "FROZEN":
        raise err("ERR_DMA_FROZEN", "DMA is frozen")
    with lock():
        wo["status"] = "CANCELLED"
        stamp_update(wo)
    return success(public(wo))
