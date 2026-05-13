"""DMA CRUD + water-balance reports."""
from flask import Blueprint, request

from db import dmas, lock, public, stamp_create, water_balance_reports
from errors import err
from middleware import get_json_body, get_pagination, require_auth
from response import success, success_list
from services.common import get_dma, get_network
from services.water_balance import create_water_balance_report


bp = Blueprint("dmas", __name__)


@bp.post("/networks/<network_id>/dmas")
@require_auth(roles={"TopologyEngineer"})
def create_dma(network_id):
    n = get_network(network_id)
    body = get_json_body()
    dma_code = body.get("dma_code")
    name = body.get("name")
    if not dma_code or not isinstance(dma_code, str):
        raise err("ERR_BAD_REQUEST", "dma_code is required")
    if not name or not isinstance(name, str):
        raise err("ERR_BAD_REQUEST", "name is required")
    # Uniqueness on dma_code within network
    for d in dmas.values():
        if d.get("network_id") == network_id and d.get("dma_code") == dma_code:
            raise err("ERR_BAD_REQUEST", "dma_code already exists in this network")
    inlets = body.get("inlet_node_codes") or []
    outlets = body.get("outlet_node_codes") or []
    if not isinstance(inlets, list) or not isinstance(outlets, list):
        raise err("ERR_BAD_REQUEST", "inlet/outlet_node_codes must be arrays")
    with lock():
        d = {
            "network_id": network_id,
            "dma_code": dma_code,
            "name": name,
            "status": "OPEN",
            "inlet_node_codes": list(inlets),
            "outlet_node_codes": list(outlets),
            "open_critical_alert_count": 0,
        }
        stamp_create(d)
        dmas[d["id"]] = d
        return success(public(d), 201)


@bp.get("/networks/<network_id>/dmas/<dma_id>")
@require_auth(roles={"TopologyEngineer", "ControlOperator", "MaintenanceSupervisor", "Auditor"})
def get_dma_endpoint(network_id, dma_id):
    d = get_dma(network_id, dma_id)
    return success(public(d))


@bp.get("/networks/<network_id>/dmas")
@require_auth(roles={"TopologyEngineer", "ControlOperator", "MaintenanceSupervisor", "Auditor"})
def list_dmas(network_id):
    get_network(network_id)
    status_filter = request.args.get("status")
    limit, offset = get_pagination()
    rows = [
        d for d in dmas.values()
        if d.get("network_id") == network_id
        and (status_filter is None or d.get("status") == status_filter)
    ]
    rows.sort(key=lambda r: r.get("created_at") or "")
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/networks/<network_id>/dmas/<dma_id>/water-balance-reports")
@require_auth(roles={"ControlOperator"})
def create_water_balance(network_id, dma_id):
    n = get_network(network_id)
    d = get_dma(network_id, dma_id)
    # Water balance reports are NOT blocked by DMA FROZEN per PRD §2.8 — wait,
    # PRD §2.8 says "every state-changing endpoint within the DMA's scope" is
    # blocked except topology rollback and clock advance. Water balance creation
    # IS state-changing (creates a report). Block it.
    if d.get("status") == "FROZEN":
        raise err("ERR_DMA_FROZEN", "DMA is frozen")
    body = get_json_body()
    with lock():
        report = create_water_balance_report(n, d, body)
        return success(public(report), 201)


@bp.get("/networks/<network_id>/dmas/<dma_id>/water-balance-reports")
@require_auth(roles={"ControlOperator", "Auditor"})
def list_water_balance(network_id, dma_id):
    d = get_dma(network_id, dma_id)
    limit, offset = get_pagination()
    rows = [r for r in water_balance_reports.values() if r.get("dma_id") == dma_id]
    rows.sort(key=lambda r: r.get("created_at") or "")
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)
