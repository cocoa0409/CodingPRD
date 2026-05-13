"""Alert read endpoints + triage workflow."""
from flask import Blueprint, g, request

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
from middleware import get_json_body, get_pagination, require_auth
from response import success, success_list
from services.audit import write_audit
from services.common import get_alert, get_network
from services.dma_posture import recompute_dma_posture
from services.sync import emit_sync_for_alert_resolved


bp = Blueprint("alerts", __name__)


@bp.get("/networks/<network_id>/alerts")
@require_auth(roles={"ControlOperator", "MaintenanceSupervisor", "Auditor"})
def list_alerts(network_id):
    get_network(network_id)
    status_f = request.args.get("status")
    severity_f = request.args.get("severity")
    dma_f = request.args.get("dma_id")
    limit, offset = get_pagination()
    rows = [
        a for a in alerts.values()
        if a.get("network_id") == network_id
        and (status_f is None or a.get("status") == status_f)
        and (severity_f is None or a.get("severity") == severity_f)
        and (dma_f is None or a.get("dma_id") == dma_f)
    ]
    rows.sort(key=lambda r: r.get("created_at") or "")
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)


@bp.get("/networks/<network_id>/alerts/<alert_id>")
@require_auth(roles={"ControlOperator", "MaintenanceSupervisor", "Auditor"})
def get_alert_endpoint(network_id, alert_id):
    a = get_alert(network_id, alert_id)
    return success(public(a))


@bp.post("/networks/<network_id>/alerts/<alert_id>/acknowledge")
@require_auth(roles={"ControlOperator"})
def acknowledge_alert(network_id, alert_id):
    a = get_alert(network_id, alert_id)
    if a.get("status") != "OPEN":
        raise err("ERR_INVALID_STATE", "alert is not OPEN")
    # FROZEN check
    if a.get("dma_id"):
        d = dmas.get(a["dma_id"])
        if d and d.get("status") == "FROZEN":
            raise err("ERR_DMA_FROZEN", "DMA is frozen")
    if a.get("severity") == "INFO":
        raise err("ERR_INVALID_STATE", "INFO alerts cannot be acknowledged")
    with lock():
        a["status"] = "ACKNOWLEDGED"
        a["acknowledged_by"] = g.user_id
        stamp_update(a)
        write_audit(
            network_id=network_id,
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="ALERT_ACK",
            resource_kind="Alert",
            resource_id=alert_id,
            detail={},
        )
    return success(public(a))


@bp.post("/networks/<network_id>/alerts/<alert_id>/resolve")
@require_auth(roles={"ControlOperator"})
def resolve_alert(network_id, alert_id):
    a = get_alert(network_id, alert_id)
    body = get_json_body()
    note = body.get("resolution_note")
    if not note or not isinstance(note, str):
        raise err("ERR_BAD_REQUEST", "resolution_note is required")
    cur = a.get("status")
    if cur not in ("OPEN", "INVESTIGATING"):
        raise err("ERR_INVALID_STATE", "alert cannot be resolved from this state")
    # PRD §3.3 / §3.6: resolving (or suppressing) a critical alert is the
    # mechanism by which a FROZEN DMA recovers to RESTRICTED/OPEN — "resolving
    # a critical alert may take open_critical_alert_count from 3 down to 2
    # (which transitions a FROZEN DMA back to RESTRICTED)". The FROZEN-blocks-
    # all-mutations rule (§2.8) therefore cannot apply to alert resolution.
    if cur == "OPEN" and a.get("severity") != "INFO":
        raise err("ERR_INVALID_STATE", "OPEN→RESOLVED only allowed for INFO alerts")
    if cur == "INVESTIGATING":
        # require: linked investigation in {CONFIRMED_LEAK, FALSE_POSITIVE}
        # OR a CLOSED_VERIFIED WorkOrder exists for the same investigation.
        linked_inv = None
        for inv in investigations.values():
            if inv.get("alert_id") == alert_id:
                linked_inv = inv
                break
        ok = False
        if linked_inv and linked_inv.get("status") in ("CONFIRMED_LEAK", "FALSE_POSITIVE"):
            ok = True
        if not ok and linked_inv:
            for wo in work_orders.values():
                if (
                    wo.get("investigation_id") == linked_inv["id"]
                    and wo.get("status") == "CLOSED_VERIFIED"
                ):
                    ok = True
                    break
        if not ok:
            raise err("ERR_INVALID_STATE", "investigation/work-order not in resolvable state")
    with lock():
        a["status"] = "RESOLVED"
        a["resolution_note"] = note
        stamp_update(a)
        write_audit(
            network_id=network_id,
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="ALERT_RESOLVED",
            resource_kind="Alert",
            resource_id=alert_id,
            detail={"note": note},
        )
        emit_sync_for_alert_resolved(a)
        if a.get("dma_id"):
            recompute_dma_posture(
                a["dma_id"],
                network_id=network_id,
                actor_role=g.user_role,
                actor_id=g.user_id,
            )
    return success(public(a))


@bp.post("/networks/<network_id>/alerts/<alert_id>/suppress")
@require_auth(roles={"ControlOperator"})
def suppress_alert(network_id, alert_id):
    a = get_alert(network_id, alert_id)
    if a.get("status") not in ("OPEN", "ACKNOWLEDGED"):
        raise err("ERR_INVALID_STATE", "alert cannot be suppressed from this state")
    # PRD §3.3 / §3.6: suppression "always recomputes the DMA's
    # open_critical_alert_count (which may flip DMA posture)" — including
    # the FROZEN → RESTRICTED relaxation. Do not gate suppression on the
    # FROZEN-blocks-mutations rule.
    body = get_json_body()
    note = body.get("resolution_note")
    if a.get("status") == "OPEN" and (not note or not isinstance(note, str)):
        raise err("ERR_BAD_REQUEST", "resolution_note is required when suppressing from OPEN")
    with lock():
        a["status"] = "SUPPRESSED"
        if note:
            a["resolution_note"] = note
        stamp_update(a)
        # Cascade: investigations OPEN/NARROWED on this alert -> FALSE_POSITIVE
        for inv in investigations.values():
            if inv.get("alert_id") == alert_id and inv.get("status") in ("OPEN", "NARROWED"):
                inv["status"] = "FALSE_POSITIVE"
                stamp_update(inv)
        write_audit(
            network_id=network_id,
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="ALERT_SUPPRESSED",
            resource_kind="Alert",
            resource_id=alert_id,
            detail={"note": note},
        )
        if a.get("dma_id"):
            recompute_dma_posture(
                a["dma_id"],
                network_id=network_id,
                actor_role=g.user_role,
                actor_id=g.user_id,
            )
    return success(public(a))


@bp.post("/networks/<network_id>/alerts/<alert_id>/investigations")
@require_auth(roles={"ControlOperator"})
def open_investigation(network_id, alert_id):
    a = get_alert(network_id, alert_id)
    if a.get("status") != "ACKNOWLEDGED":
        raise err("ERR_INVALID_STATE", "alert is not ACKNOWLEDGED")
    if a.get("severity") not in ("WARNING", "CRITICAL"):
        raise err("ERR_INVALID_STATE", "investigation requires WARNING/CRITICAL severity")
    if a.get("dma_id"):
        d = dmas.get(a["dma_id"])
        if d and d.get("status") == "FROZEN":
            raise err("ERR_DMA_FROZEN", "DMA is frozen")
    for inv in investigations.values():
        if inv.get("alert_id") == alert_id and inv.get("status") not in (
            "CONFIRMED_LEAK", "FALSE_POSITIVE",
        ):
            raise err("ERR_INVALID_STATE", "non-terminal investigation already exists")
    with lock():
        inv = {
            "alert_id": alert_id,
            "dma_id": a.get("dma_id"),
            "status": "OPEN",
            "water_balance_loss_lps": None,
            "min_night_flow_lps": None,
            "pressure_gradient_anomaly_segments": [],
            "suspected_segment_codes": [],
            "assigned_technician_id": None,
        }
        stamp_create(inv)
        investigations[inv["id"]] = inv
        # Parent alert ACKNOWLEDGED -> INVESTIGATING
        a["status"] = "INVESTIGATING"
        stamp_update(a)
        return success(public(inv), 201)
