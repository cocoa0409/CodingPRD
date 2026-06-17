"""MaterialOrder endpoints: fetch, list, backorder, reorder, receive."""
from flask import Blueprint, request

import clock
from db import db, touch
from errors import err
from middleware import require_roles
from response import ok, ok_list
from services import calc, serialize
from services.helpers import pagination, paginate, sort_by_created

bp = Blueprint("material_orders", __name__)


@bp.get("/flooring/material-orders/<mid>")
@require_roles("Admin", "SalesRep", "Scheduler")
def get_material_order(mid):
    with db.lock:
        m = db.material_orders.get(mid)
        if m is None:
            raise err("ERR_NOT_FOUND", "Material order not found.")
        return ok(serialize.material_order_view(m))


@bp.get("/flooring/material-orders")
@require_roles("Admin", "SalesRep", "Scheduler")
def list_material_orders():
    limit, offset = pagination()
    job_id = request.args.get("job_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    with db.lock:
        items = list(db.material_orders.values())
        if job_id is not None:
            items = [m for m in items if m["job_id"] == job_id]
        if product_id is not None:
            items = [m for m in items if m["product_id"] == product_id]
        if status is not None:
            items = [m for m in items if m["status"] == status]
        items = sort_by_created(items)
        page, total = paginate(items, limit, offset)
        views = [serialize.material_order_view(m) for m in page]
    return ok_list(views, limit, offset, total)


@bp.post("/flooring/material-orders/<mid>/backorder")
@require_roles("Scheduler", "Admin")
def backorder(mid):
    with db.lock:
        m = db.material_orders.get(mid)
        if m is None:
            raise err("ERR_NOT_FOUND", "Material order not found.")
        if m["status"] != "ORDERED":
            raise err("ERR_INVALID_STATE", "Only an ORDERED order can be backordered.")
        m["status"] = "BACKORDERED"
        m["backorder_count"] = m["backorder_count"] + 1
        touch(m)
        return ok(serialize.material_order_view(m))


@bp.post("/flooring/material-orders/<mid>/reorder")
@require_roles("Scheduler", "Admin")
def reorder(mid):
    with db.lock:
        m = db.material_orders.get(mid)
        if m is None:
            raise err("ERR_NOT_FOUND", "Material order not found.")
        if m["status"] != "BACKORDERED":
            raise err("ERR_INVALID_STATE", "Only a BACKORDERED order can be reordered.")
        m["status"] = "ORDERED"
        m["expected_ready_date"] = calc.ready_date(m["lead_time_days"])
        touch(m)
        return ok(serialize.material_order_view(m))


@bp.post("/flooring/material-orders/<mid>/receive")
@require_roles("Scheduler", "Admin")
def receive(mid):
    with db.lock:
        m = db.material_orders.get(mid)
        if m is None:
            raise err("ERR_NOT_FOUND", "Material order not found.")
        if m["status"] != "ORDERED":
            raise err("ERR_INVALID_STATE", "Only an ORDERED order can be received.")
        ready_dt = clock.parse(m["expected_ready_date"])
        if clock.now() < ready_dt:
            raise err("ERR_MATERIAL_NOT_READY", "Material cannot be received before its ready date.")
        m["status"] = "RECEIVED"
        touch(m)
        return ok(serialize.material_order_view(m))
