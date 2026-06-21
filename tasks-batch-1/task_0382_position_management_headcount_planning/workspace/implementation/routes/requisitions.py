"""Requisition endpoints: open (nested), approve, close, cancel, get, list
(PRD §3.6)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from response import success, list_success
from services import serialize, calc
from services.common import (
    get_body, require_string, require_enum, fetch, paginate,
    base_common_fields, bump,
)

bp = Blueprint("requisitions", __name__)

ALL_ROLES = ["HRBP", "HRDirector", "FinanceController", "CompensationAnalyst"]


@bp.post("/positions/<position_id>/requisitions")
def open_requisition(position_id):
    require_auth(["HRBP"])
    pos = fetch(db.positions, position_id)
    body = get_body()
    req_type = require_enum(body, "req_type", {"NEW_HIRE", "BACKFILL"})
    justification = require_string(body, "justification")

    rec = base_common_fields()
    rec.update({
        "position_id": position_id,
        "req_type": req_type,
        "justification": justification,
        "status": "OPEN",
    })
    db.requisitions[rec["id"]] = rec
    return success(serialize.requisition_out(rec), status=201)


@bp.get("/positions/<position_id>/requisitions")
def list_position_requisitions(position_id):
    require_auth(ALL_ROLES)
    fetch(db.positions, position_id)
    records = [r for r in db.requisitions.values() if r["position_id"] == position_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.requisition_out(r) for r in page], limit, offset, total)


@bp.get("/requisitions/<requisition_id>")
def get_requisition(requisition_id):
    require_auth(ALL_ROLES)
    rec = fetch(db.requisitions, requisition_id)
    return success(serialize.requisition_out(rec))


@bp.get("/requisitions")
def list_requisitions():
    require_auth(ALL_ROLES)
    records = list(db.requisitions.values())
    for field in ("position_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.requisition_out(r) for r in page], limit, offset, total)


@bp.post("/requisitions/<requisition_id>/approve")
def approve_requisition(requisition_id):
    require_auth(["FinanceController"])
    req = fetch(db.requisitions, requisition_id)
    pos = db.positions.get(req["position_id"])
    # State (priority 6).
    if req["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "requisition must be OPEN to approve")
    # Frozen gate (priority 7).
    if pos is not None and calc.cost_center_posture(pos["cost_center_id"]) == "FROZEN":
        raise err("ERR_COST_CENTER_FROZEN", "owning cost center is frozen")
    # Owning position must be FUNDED.
    if pos is None or pos["lifecycle_status"] != "FUNDED":
        raise err("ERR_POSITION_NOT_FUNDED", "owning position must be FUNDED")
    req["status"] = "APPROVED"
    bump(req)
    return success(serialize.requisition_out(req))


@bp.post("/requisitions/<requisition_id>/close")
def close_requisition(requisition_id):
    require_auth(["HRBP"])
    req = fetch(db.requisitions, requisition_id)
    pos = db.positions.get(req["position_id"])
    # State (priority 6).
    if req["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "requisition must be APPROVED to close")
    # Owning position must be FILLED.
    if pos is None or pos["occupancy_status"] != "FILLED":
        raise err("ERR_POSITION_NOT_FILLED", "owning position must be FILLED")
    req["status"] = "CLOSED"
    bump(req)
    return success(serialize.requisition_out(req))


@bp.post("/requisitions/<requisition_id>/cancel")
def cancel_requisition(requisition_id):
    require_auth(["HRBP"])
    req = fetch(db.requisitions, requisition_id)
    # State (priority 6).
    if req["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "requisition must be OPEN to cancel")
    req["status"] = "CANCELLED"
    bump(req)
    return success(serialize.requisition_out(req))
