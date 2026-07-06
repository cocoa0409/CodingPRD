"""WorkOrder endpoints — production + addressing dimensions."""

from flask import Blueprint

import db
import errors
import middleware
import models
import response as resp
import services
import util

bp = Blueprint("work_orders", __name__)


PRODUCTION_ORDER = ["NOT_STARTED", "PRINTING", "FINISHING", "COMPLETED"]
ADDRESSING_ORDER = ["PENDING", "IN_PROGRESS", "COMPLETED"]


def _order_for_workorder(wo: dict):
    return db.orders.get(wo["order_id"])


@bp.route("/work-orders/<wid>/production", methods=["POST"])
def advance_production(wid):
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    wo = models.get_work_order(wid)
    body = util.get_body()
    new_status = util.get_enum(body, "new_status", PRODUCTION_ORDER[1:])  # can't move TO NOT_STARTED

    o = _order_for_workorder(wo)
    if not o:
        errors.raise_error(errors.ERR_ORDER_NOT_FOUND, "parent order not found")

    if o["status"] in ("CANCELLED", "DELIVERED", "SHIPPED"):
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "parent order is terminal")

    cur = wo["production_status"]
    if cur == "COMPLETED":
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "production already completed")

    cur_idx = PRODUCTION_ORDER.index(cur)
    new_idx = PRODUCTION_ORDER.index(new_status)
    if new_idx != cur_idx + 1:
        errors.raise_error(errors.ERR_INVALID_STATE, "invalid production transition")

    if new_status == "PRINTING":
        # Parent order must be IN_PRODUCTION
        if o["status"] != "IN_PRODUCTION":
            errors.raise_error(errors.ERR_INVALID_STATE, "parent order must be IN_PRODUCTION")
        press_id = util.get_str(body, "press_id")
        press_slot_start_dt = util.get_iso_datetime(body, "press_slot_start")
        press_slot_end_dt = util.get_iso_datetime(body, "press_slot_end")
        if press_slot_end_dt <= press_slot_start_dt:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "press_slot_end must be > press_slot_start")
        # Check overlap on same press_id (closed interval + adjacency)
        for other in db.work_orders.values():
            if other["id"] == wo["id"]:
                continue
            if other.get("press_id") != press_id:
                continue
            if other.get("press_slot_start") is None or other.get("press_slot_end") is None:
                continue
            try:
                ostart = db.parse_iso(other["press_slot_start"])
                oend = db.parse_iso(other["press_slot_end"])
            except Exception:
                continue
            # Closed intervals overlap if starts <= end_other AND ends >= start_other
            # (adjacency at boundary rejected)
            if press_slot_start_dt <= oend and press_slot_end_dt >= ostart:
                errors.raise_error(errors.ERR_PRESS_SLOT_OVERLAP, "press slot overlaps existing work order")
        wo["press_id"] = press_id
        wo["press_slot_start"] = db.format_iso(press_slot_start_dt)
        wo["press_slot_end"] = db.format_iso(press_slot_end_dt)

    wo["production_status"] = new_status
    models.bump(wo)

    # If completed, attempt cascade
    if new_status == "COMPLETED":
        services.try_cascade_ready_to_ship(o, wo)

    return resp.ok(wo)


@bp.route("/work-orders/<wid>/addressing", methods=["POST"])
def advance_addressing(wid):
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    wo = models.get_work_order(wid)
    body = util.get_body()
    new_status = util.get_enum(body, "new_status", ["IN_PROGRESS", "COMPLETED"])

    o = _order_for_workorder(wo)
    if not o:
        errors.raise_error(errors.ERR_ORDER_NOT_FOUND, "parent order not found")
    if o["status"] in ("CANCELLED", "DELIVERED", "SHIPPED"):
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "parent order is terminal")

    cur = wo["addressing_status"]
    if cur == "NOT_APPLICABLE":
        errors.raise_error(errors.ERR_INVALID_STATE, "addressing not applicable to this order")
    if cur == "COMPLETED":
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "addressing already completed")

    cur_idx = ADDRESSING_ORDER.index(cur)
    new_idx = ADDRESSING_ORDER.index(new_status)
    if new_idx != cur_idx + 1:
        errors.raise_error(errors.ERR_INVALID_STATE, "invalid addressing transition")

    if new_status == "IN_PROGRESS":
        # Must have at least one AddressingJob on this order (non-cancelled)
        order_jobs = [
            a for a in models.order_addressing_jobs(o["id"])
            if a["status"] not in ("CANCELLED",)
        ]
        if not order_jobs:
            errors.raise_error(errors.ERR_INVALID_STATE, "order has no addressing jobs")
        # Capacity check: sum of AddressingJob.quantity across ALL AddressingJobs whose
        # scheduled_date == today AND whose parent order's WorkOrder.addressing_status is
        # currently IN_PROGRESS, plus the quantities that would enter IN_PROGRESS by this
        # transition, must not exceed DAILY_ADDRESSING_CAPACITY.
        today = db.get_now().date().isoformat()
        current_today_total = 0
        for other_wo in db.work_orders.values():
            if other_wo["id"] == wo["id"]:
                continue
            if other_wo.get("addressing_status") != "IN_PROGRESS":
                continue
            for a in models.order_addressing_jobs(other_wo["order_id"]):
                if a["scheduled_date"] == today and a["status"] == "IN_PROGRESS":
                    current_today_total += int(a["quantity"])
        # Add the quantities that would enter IN_PROGRESS today from this order
        would_add = sum(
            int(a["quantity"]) for a in order_jobs
            if a["scheduled_date"] == today
        )
        if current_today_total + would_add > services.DAILY_ADDRESSING_CAPACITY:
            errors.raise_error(errors.ERR_ADDRESSING_CAPACITY_EXCEEDED, "daily addressing capacity exceeded")

        # Cascade all jobs on this order to IN_PROGRESS
        for a in order_jobs:
            a["status"] = "IN_PROGRESS"
            models.bump(a)
    elif new_status == "COMPLETED":
        for a in models.order_addressing_jobs(o["id"]):
            if a["status"] == "IN_PROGRESS":
                a["status"] = "COMPLETED"
                models.bump(a)

    wo["addressing_status"] = new_status
    models.bump(wo)
    if new_status == "COMPLETED":
        services.try_cascade_ready_to_ship(o, wo)
    return resp.ok(wo)


@bp.route("/work-orders/<wid>", methods=["GET"])
def get_work_order(wid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer"])
    wo = models.get_work_order(wid)
    if role == "Customer":
        o = db.orders.get(wo["order_id"])
        if not o or o["customer_id"] != user_id:
            errors.raise_error(errors.ERR_UNAUTHORIZED, "not your work order")
    return resp.ok(wo)


@bp.route("/orders/<oid>/work-orders", methods=["GET"])
def list_order_work_orders(oid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer"])
    o = models.get_order(oid)
    if role == "Customer":
        middleware.require_owner(user_id, o["customer_id"])
    limit, offset = util.get_pagination()
    items = [w for w in db.work_orders.values() if w["order_id"] == oid]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)
