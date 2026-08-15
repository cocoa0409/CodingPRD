"""DisplacementPlan endpoints."""

from datetime import timedelta
from flask import Blueprint, request

from clock import now, now_iso_ms, parse_iso
from db import DB
from middleware import (
    require_role, base_fields, paginate, err, touch,
)
from response import success_object, success_list
from errors import (
    ERR_DISPLACEMENT_PLAN_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_PLAN_NOT_NOTIFIABLE, ERR_PLAN_NOT_NOTICED, ERR_NOTICE_LEAD_TIME_SHORT,
)

bp = Blueprint("displacement_plans", __name__)


def serialize_plan(p):
    return {
        "id": p["id"],
        "work_order_id": p["work_order_id"],
        "vehicles_to_move": p["vehicles_to_move"],
        "notice_sent_at": p["notice_sent_at"],
        "access_block_start": p["access_block_start"],
        "access_block_end": p["access_block_end"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.get("/api/displacement-plans")
def list_plans():
    user_id, role = require_role("OfficeAdmin", "Dispatcher", "CrewLead", "Customer")
    items = list(DB.displacement_plans.values())
    if role == "Customer":
        own_props = {p["id"] for p in DB.properties.values() if p["customer_id"] == user_id}
        own_wos = {w["id"] for w in DB.work_orders.values() if w["property_id"] in own_props}
        items = [p for p in items if p["work_order_id"] in own_wos]
    wo_filter = request.args.get("work_order_id")
    status_filter = request.args.get("status")
    if wo_filter:
        items = [p for p in items if p["work_order_id"] == wo_filter]
    if status_filter:
        items = [p for p in items if p["status"] == status_filter]
    items.sort(key=lambda p: p["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_plan(p) for p in page], limit, offset, total)


@bp.get("/api/displacement-plans/<planId>")
def get_plan(planId):
    user_id, role = require_role("OfficeAdmin", "Dispatcher", "CrewLead", "Customer")
    p = DB.displacement_plans.get(planId)
    if p is None:
        raise err(ERR_DISPLACEMENT_PLAN_NOT_FOUND, 404, "Displacement plan id does not exist")
    if role == "Customer":
        wo = DB.work_orders.get(p["work_order_id"])
        prop = DB.properties.get(wo["property_id"]) if wo else None
        if prop is None or prop["customer_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, 403,
                      "Customer acting on a resource owned by a different customer")
    return success_object(serialize_plan(p))


@bp.post("/api/displacement-plans/<planId>/send-notice")
def send_notice(planId):
    require_role("Dispatcher")
    p = DB.displacement_plans.get(planId)
    if p is None:
        raise err(ERR_DISPLACEMENT_PLAN_NOT_FOUND, 404, "Displacement plan id does not exist")
    if p["status"] not in ("NOTICE_PENDING", "STALE"):
        raise err(ERR_PLAN_NOT_NOTIFIABLE, 409,
                  "send-notice requires NOTICE_PENDING or STALE")
    # 48h lead time
    block_start = parse_iso(p["access_block_start"])
    if now() + timedelta(hours=48) > block_start:
        raise err(ERR_NOTICE_LEAD_TIME_SHORT, 422,
                  "Notice sent less than 48h before access_block_start")
    p["status"] = "NOTICE_SENT"
    p["notice_sent_at"] = now_iso_ms()
    touch(p)
    return success_object(serialize_plan(p))


@bp.post("/api/displacement-plans/<planId>/confirm-cleared")
def confirm_cleared(planId):
    require_role("Dispatcher")
    p = DB.displacement_plans.get(planId)
    if p is None:
        raise err(ERR_DISPLACEMENT_PLAN_NOT_FOUND, 404, "Displacement plan id does not exist")
    if p["status"] != "NOTICE_SENT":
        raise err(ERR_PLAN_NOT_NOTICED, 409, "confirm-cleared requires NOTICE_SENT")
    p["status"] = "CLEARED"
    touch(p)
    return success_object(serialize_plan(p))
