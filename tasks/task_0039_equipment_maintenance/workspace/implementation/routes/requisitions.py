"""Requisition routes."""
from flask import Blueprint

from db import db, new_id
from errors import (
    ERR_BAD_REQUEST,
    ERR_CROSS_SITE_REFERENCE,
    ERR_INSUFFICIENT_AVAILABLE,
    ERR_INSUFFICIENT_STOCK,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_RETURN_QTY_INVALID,
    raise_err,
)
from middleware import require_role
from response import success_object
from services.audit import append_audit
from services.calculations import replenish_eval
from services.common import (
    get_json_body,
    get_requisition_or_404,
    get_site_or_404,
    get_work_order_or_404,
)
from services.serialize import serialize_requisition

bp = Blueprint("requisitions", __name__)


@bp.route("/sites/<site_id>/work-orders/<wo_id>/requisitions", methods=["POST"])
def create_requisition(site_id, wo_id):
    require_role(["Technician", "Storekeeper"])
    get_site_or_404(site_id)
    w = get_work_order_or_404(site_id, wo_id)

    body = get_json_body()
    part_id = body.get("part_id")
    qty = body.get("qty")
    if not isinstance(part_id, str) or not part_id:
        raise_err(ERR_BAD_REQUEST, "part_id is required")
    if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
        raise_err(ERR_BAD_REQUEST, "qty must be a positive integer")

    sp = db.spare_parts.get(part_id)
    if sp is None:
        raise_err(ERR_NOT_FOUND, "spare part not found")
    if sp["site_id"] != site_id:
        raise_err(ERR_CROSS_SITE_REFERENCE, "spare part belongs to a different site")

    if w["status"] not in {"PENDING", "IN_PROGRESS", "PAUSED"}:
        raise_err(ERR_INVALID_STATE, "WorkOrder must be open to add requisitions")

    available = sp["stock_on_hand"] - sp["stock_reserved"]
    if available < qty:
        raise_err(ERR_INSUFFICIENT_AVAILABLE, "available stock insufficient")

    sp["stock_reserved"] += qty

    rid = new_id()
    clock = db.site_clock(site_id)
    r = {
        "id": rid,
        "created_at": clock,
        "updated_at": clock,
        "version": 1,
        "work_order_id": wo_id,
        "part_id": part_id,
        "qty": qty,
        "status": "RESERVED",
        "unit_cost_cents_at_issue": None,
        "returned_qty": 0,
    }
    db.requisitions[rid] = r
    replenish_eval(sp)
    return success_object(serialize_requisition(r), 201)


@bp.route("/sites/<site_id>/work-orders/<wo_id>/requisitions/<req_id>/issue", methods=["POST"])
def issue(site_id, wo_id, req_id):
    require_role(["Storekeeper"])
    get_site_or_404(site_id)
    w = get_work_order_or_404(site_id, wo_id)
    r = get_requisition_or_404(site_id, wo_id, req_id)

    if r["status"] != "RESERVED":
        raise_err(ERR_INVALID_STATE, "Requisition must be RESERVED to issue")
    if w["status"] not in {"PENDING", "IN_PROGRESS", "PAUSED"}:
        raise_err(ERR_INVALID_STATE, "WorkOrder must be open to issue")

    sp = db.spare_parts.get(r["part_id"])
    if sp is None:
        raise_err(ERR_NOT_FOUND, "spare part not found")
    if sp["stock_on_hand"] < r["qty"]:
        raise_err(ERR_INSUFFICIENT_STOCK, "stock_on_hand insufficient")

    clock = db.site_clock(site_id)
    r["unit_cost_cents_at_issue"] = sp["unit_cost_cents"]
    sp["stock_on_hand"] -= r["qty"]
    sp["stock_reserved"] -= r["qty"]
    if sp["stock_reserved"] < 0:
        sp["stock_reserved"] = 0
    replenish_eval(sp)

    r["status"] = "ISSUED"
    r["updated_at"] = clock
    r["version"] += 1

    append_audit(site_id, "PARTS_ISSUED", r["id"], "RESERVED", "ISSUED")
    return success_object(serialize_requisition(r))


@bp.route("/sites/<site_id>/work-orders/<wo_id>/requisitions/<req_id>/return", methods=["POST"])
def return_req(site_id, wo_id, req_id):
    require_role(["Storekeeper"])
    get_site_or_404(site_id)
    w = get_work_order_or_404(site_id, wo_id)
    r = get_requisition_or_404(site_id, wo_id, req_id)

    body = get_json_body()
    rq = body.get("returned_qty")
    if not isinstance(rq, int) or isinstance(rq, bool) or rq <= 0:
        raise_err(ERR_RETURN_QTY_INVALID, "returned_qty must be > 0")
    if rq > (r["qty"] - r["returned_qty"]):
        raise_err(ERR_RETURN_QTY_INVALID, "returned_qty exceeds remaining quantity")

    if r["status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE, "Requisition must be ISSUED to return")

    # Work order must be IN_PROGRESS, PAUSED, or COMPLETED-but-not-CLOSED
    allowed = w["status"] in {"IN_PROGRESS", "PAUSED"} or (w["status"] == "COMPLETED" and not w.get("closed_at"))
    if not allowed:
        raise_err(ERR_INVALID_STATE, "WorkOrder state does not allow return")

    sp = db.spare_parts.get(r["part_id"])
    clock = db.site_clock(site_id)
    r["returned_qty"] += rq
    if sp is not None:
        sp["stock_on_hand"] += rq
        replenish_eval(sp)
    # Note: spec says status remains ISSUED with non-zero returned_qty
    # (parts_cost calculation uses qty - returned_qty)

    r["updated_at"] = clock
    r["version"] += 1

    append_audit(site_id, "PARTS_RETURNED", r["id"], "ISSUED", "ISSUED")
    return success_object(serialize_requisition(r))


@bp.route("/sites/<site_id>/work-orders/<wo_id>/requisitions/<req_id>/cancel", methods=["POST"])
def cancel_req(site_id, wo_id, req_id):
    require_role(["Technician", "Storekeeper"])
    get_site_or_404(site_id)
    w = get_work_order_or_404(site_id, wo_id)
    r = get_requisition_or_404(site_id, wo_id, req_id)
    if r["status"] != "RESERVED":
        raise_err(ERR_INVALID_STATE, "Requisition must be RESERVED to cancel")

    sp = db.spare_parts.get(r["part_id"])
    clock = db.site_clock(site_id)
    if sp is not None:
        sp["stock_reserved"] = max(0, sp["stock_reserved"] - r["qty"])
        replenish_eval(sp)

    r["status"] = "CANCELLED"
    r["updated_at"] = clock
    r["version"] += 1

    append_audit(site_id, "WORK_ORDER_STATE_CHANGE", r["id"], "RESERVED", "CANCELLED")
    return success_object(serialize_requisition(r))
