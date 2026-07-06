"""WorkOrder: create, list, get, assign, start, complete, cancel, invoice, mark-paid."""

from flask import Blueprint, request

import db
from auth import require_role
from clock import get_now_iso
from entities import bump, new_work_order
from errors import raise_error
from response import success
from utils import (paginate, require_fields, require_int, require_str,
                   optional_str, require_json)

bp = Blueprint("work_orders", __name__)


@bp.route("/work-orders", methods=["POST"])
@require_role("HOAManager")
def create_work_order():
    body = require_json(request)
    require_fields(body, "title", "cost_estimate_cents")
    title = require_str(body, "title")
    cost = require_int(body, "cost_estimate_cents", minimum=0)
    related = optional_str(body, "related_property_id", default=None)
    if related is not None:
        if related not in db.properties:
            raise_error("ERR_FK_NOT_FOUND", "related_property_id does not resolve")
    row = new_work_order(title, cost, related, "MANUAL", get_now_iso())
    db.work_orders[row["id"]] = row
    return success(row, status=201)


@bp.route("/work-orders/<wid>", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def get_work_order(wid):
    w = db.work_orders.get(wid)
    if not w:
        raise_error("ERR_NOT_FOUND", "work order not found")
    return success(w)


@bp.route("/work-orders", methods=["GET"])
@require_role("BoardMember", "HOAManager")
def list_work_orders():
    rp = request.args.get("related_property_id")
    items = list(db.work_orders.values())
    if rp:
        items = [w for w in items if w.get("related_property_id") == rp]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)


@bp.route("/work-orders/<wid>/assign", methods=["POST"])
@require_role("HOAManager")
def assign_work_order(wid):
    body = require_json(request)
    require_fields(body, "assigned_vendor_id")
    vendor = require_str(body, "assigned_vendor_id")
    w = db.work_orders.get(wid)
    if not w:
        raise_error("ERR_NOT_FOUND", "work order not found")
    if w["work_status"] != "NEW":
        raise_error("ERR_INVALID_STATE", "work order must be NEW to assign")
    w["assigned_vendor_id"] = vendor
    w["work_status"] = "ASSIGNED"
    bump(w, get_now_iso())
    return success(w)


@bp.route("/work-orders/<wid>/start", methods=["POST"])
@require_role("HOAManager")
def start_work_order(wid):
    require_json(request)
    w = db.work_orders.get(wid)
    if not w:
        raise_error("ERR_NOT_FOUND", "work order not found")
    if w["work_status"] != "ASSIGNED":
        raise_error("ERR_INVALID_STATE", "work order must be ASSIGNED to start")
    w["work_status"] = "IN_PROGRESS"
    bump(w, get_now_iso())
    return success(w)


@bp.route("/work-orders/<wid>/complete", methods=["POST"])
@require_role("HOAManager")
def complete_work_order(wid):
    require_json(request)
    w = db.work_orders.get(wid)
    if not w:
        raise_error("ERR_NOT_FOUND", "work order not found")
    if w["work_status"] != "IN_PROGRESS":
        raise_error("ERR_INVALID_STATE", "work order must be IN_PROGRESS to complete")
    w["work_status"] = "COMPLETED"
    bump(w, get_now_iso())
    return success(w)


@bp.route("/work-orders/<wid>/cancel", methods=["POST"])
@require_role("HOAManager")
def cancel_work_order(wid):
    require_json(request)
    w = db.work_orders.get(wid)
    if not w:
        raise_error("ERR_NOT_FOUND", "work order not found")
    if w["work_status"] not in ("NEW", "ASSIGNED"):
        raise_error("ERR_INVALID_STATE", "work order must be NEW or ASSIGNED to cancel")
    if w["payment_status"] != "UNBILLED":
        raise_error("ERR_INVALID_STATE", "work order payment must be UNBILLED to cancel")
    w["work_status"] = "CANCELLED"
    bump(w, get_now_iso())
    return success(w)


@bp.route("/work-orders/<wid>/invoice", methods=["POST"])
@require_role("HOAManager")
def invoice_work_order(wid):
    require_json(request)
    w = db.work_orders.get(wid)
    if not w:
        raise_error("ERR_NOT_FOUND", "work order not found")
    if w["payment_status"] != "UNBILLED":
        raise_error("ERR_INVALID_STATE", "work order payment must be UNBILLED to invoice")
    if w["work_status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise_error("ERR_INVALID_STATE", "work order work status must be IN_PROGRESS or COMPLETED to invoice")
    w["payment_status"] = "INVOICED"
    bump(w, get_now_iso())
    return success(w)


@bp.route("/work-orders/<wid>/mark-paid", methods=["POST"])
@require_role("HOAManager")
def mark_paid_work_order(wid):
    require_json(request)
    w = db.work_orders.get(wid)
    if not w:
        raise_error("ERR_NOT_FOUND", "work order not found")
    if w["payment_status"] != "INVOICED":
        raise_error("ERR_INVALID_STATE", "work order payment must be INVOICED to mark paid")
    w["payment_status"] = "PAID"
    bump(w, get_now_iso())
    return success(w)
