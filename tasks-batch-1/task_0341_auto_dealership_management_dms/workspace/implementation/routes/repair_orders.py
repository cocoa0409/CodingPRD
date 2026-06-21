from flask import Blueprint, request

import db
import response
from errors import err
from middleware import require_roles
from routes.lookup import get_fk, get_path
from services import serialize
from util import (base_record, get_json_body, paginate, parse_dt, parse_iso,
                  parse_pagination, require_enum, require_int, require_str, touch)

bp = Blueprint("repair_orders", __name__)


@bp.post("/repair-orders")
@require_roles("ServiceAdvisor")
def open_repair_order():
    body = get_json_body()
    vehicle_id = require_str(body, "vehicle_id")
    deal_id = body.get("deal_id")
    if deal_id is not None and not isinstance(deal_id, str):
        raise err("ERR_INVALID_REQUEST", "deal_id must be a string or null")
    ro_type = require_enum(body, "ro_type", ("RECON", "WE_OWE", "RETAIL"))
    bay = require_enum(body, "bay", ("BAY_1", "BAY_2", "BAY_3"))
    start_at = parse_dt(body, "scheduled_start_at")
    end_at = parse_dt(body, "scheduled_end_at")
    parts_cents = require_int(body, "parts_cents", required=False, minimum=0, default=0)
    labor_cents = require_int(body, "labor_cents", required=False, minimum=0, default=0)

    # FK existence (priority 4).
    get_fk(db.vehicles, vehicle_id)
    if deal_id is not None:
        get_fk(db.deals, deal_id)

    # Bay overlap (priority 12): closed interval [start, end], no buffer.
    for ro in db.repair_orders.values():
        if ro["bay"] != bay or ro["status"] != "OPEN":
            continue
        ex_start = parse_iso(ro["scheduled_start_at"])
        ex_end = parse_iso(ro["scheduled_end_at"])
        if start_at <= ex_end and ex_start <= end_at:
            raise err("ERR_BAY_OVERLAP", "Bay slot overlaps another open repair order")

    rec = base_record()
    rec.update({
        "vehicle_id": vehicle_id,
        "deal_id": deal_id,
        "ro_type": ro_type,
        "bay": bay,
        "scheduled_start_at": body["scheduled_start_at"],
        "scheduled_end_at": body["scheduled_end_at"],
        "parts_cents": parts_cents,
        "labor_cents": labor_cents,
        "total_cents": parts_cents + labor_cents,
        "status": "OPEN",
    })
    db.repair_orders[rec["id"]] = rec
    return response.success(serialize.repair_order(rec), status=201)


@bp.get("/repair-orders/<rid>")
@require_roles("ServiceAdvisor", "FinanceManager", "SalesManager")
def get_repair_order(rid):
    rec = get_path(db.repair_orders, rid)
    return response.success(serialize.repair_order(rec))


@bp.get("/repair-orders")
@require_roles("ServiceAdvisor", "FinanceManager", "SalesManager")
def list_repair_orders():
    limit, offset = parse_pagination()
    items = list(db.repair_orders.values())
    for key in ("vehicle_id", "deal_id", "bay"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    page, total, has_more = paginate(items, limit, offset)
    return response.success_list([serialize.repair_order(r) for r in page], limit, offset, total, has_more)


@bp.post("/repair-orders/<rid>/close")
@require_roles("ServiceAdvisor")
def close_repair_order(rid):
    rec = get_path(db.repair_orders, rid)
    if rec["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Repair order is not OPEN")
    rec["status"] = "CLOSED"
    rec["total_cents"] = rec["parts_cents"] + rec["labor_cents"]
    touch(rec)
    return response.success(serialize.repair_order(rec))


@bp.post("/repair-orders/<rid>/cancel")
@require_roles("ServiceAdvisor")
def cancel_repair_order(rid):
    rec = get_path(db.repair_orders, rid)
    if rec["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Repair order is not OPEN")
    rec["status"] = "CANCELLED"
    touch(rec)
    return response.success(serialize.repair_order(rec))
