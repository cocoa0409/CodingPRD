"""Shop days and fulfillment legs (production / pickup / delivery)."""
from flask import Blueprint, request

from db import db
from errors import err
import errors
from middleware import get_identity, require_roles
from helpers import (base_record, get_body, require_string, require_number,
                     require_enum, get_resource_or_404, get_fk_or_404,
                     parse_pagination, paginate, touch, serialize, serialize_list)
from response import ok_object, ok_array
from services import order_line_items, order_material_orders, recompute_shop_day_status

bp = Blueprint("scheduling", __name__)


# --------------------------------------------------------------------------
# Shop days
# --------------------------------------------------------------------------
@bp.post("/shop-days")
def create_shop_day():
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    body = get_body()
    work_date = require_string(body, "work_date")
    capacity = require_number(body, "labor_capacity_hours")
    if capacity <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "labor_capacity_hours must be > 0")
    # Uniqueness among non-CANCELLED shop days (priority 33).
    for d in db.shop_days.values():
        if d["work_date"] == work_date and d["status"] != "CANCELLED":
            raise err(errors.ERR_DUPLICATE_SHOP_DAY,
                      "A non-cancelled ShopDay already exists for this work_date")
    rec = base_record(common=True)
    rec.update({
        "work_date": work_date,
        "labor_capacity_hours": capacity,
        "booked_hours": 0,
        "status": "OPEN",
    })
    db.shop_days[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/shop-days/<sid>")
def get_shop_day(sid):
    _, role = get_identity()
    require_roles(role, {"ShopManager", "Estimator"})
    rec = get_resource_or_404(db.shop_days, sid)
    return ok_object(serialize(rec), 200)


@bp.get("/shop-days")
def list_shop_days():
    _, role = get_identity()
    require_roles(role, {"ShopManager", "Estimator"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    matches = list(db.shop_days.values())
    if status is not None:
        matches = [d for d in matches if d["status"] == status]
    page, total = paginate(matches, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/shop-days/<sid>/close")
def close_shop_day(sid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    rec = get_resource_or_404(db.shop_days, sid)
    if rec["status"] not in ("OPEN", "FULL"):
        raise err(errors.ERR_INVALID_STATE, "ShopDay must be OPEN or FULL to close")
    rec["status"] = "CLOSED"
    touch(rec)
    return ok_object(serialize(rec), 200)


# --------------------------------------------------------------------------
# Fulfillment legs
# --------------------------------------------------------------------------
LEG_KINDS = {"PRODUCTION", "PICKUP", "DELIVERY"}


@bp.post("/fulfillment-legs")
def create_fulfillment_leg():
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    body = get_body()
    work_order_id = require_string(body, "work_order_id")
    kind = require_enum(body, "kind", LEG_KINDS)
    shop_day_id = body.get("shop_day_id")
    window_start = body.get("scheduled_window_start")
    window_end = body.get("scheduled_window_end")
    if shop_day_id is not None and not isinstance(shop_day_id, str):
        raise err(errors.ERR_INVALID_REQUEST, "shop_day_id must be a string")

    # FK existence (priority 12).
    get_fk_or_404(db.work_orders, work_order_id)
    if kind == "PRODUCTION":
        if not isinstance(shop_day_id, str):
            raise err(errors.ERR_INVALID_REQUEST,
                      "PRODUCTION leg requires shop_day_id")
        get_fk_or_404(db.shop_days, shop_day_id)

    if kind == "PRODUCTION":
        return _create_production_leg(work_order_id, shop_day_id)
    return _create_logistics_leg(work_order_id, kind, window_start, window_end)


def _create_production_leg(work_order_id, shop_day_id):
    wo = db.work_orders[work_order_id]
    day = db.shop_days[shop_day_id]

    # State (priority 20): order must be APPROVED to start production.
    if wo["status"] != "APPROVED":
        raise err(errors.ERR_INVALID_STATE,
                  "PRODUCTION leg requires the order to be APPROVED")
    # Cross-entity: no ORDERED material outstanding (priority 22).
    if any(mo["status"] == "ORDERED" for mo in order_material_orders(work_order_id)):
        raise err(errors.ERR_MATERIALS_OUTSTANDING,
                  "A material order is still ORDERED")

    # Capacity (priority 40): not FULL/CLOSED; aggregate booked + order hours
    # must not exceed capacity.
    order_hours = sum(li["labor_hours"] for li in order_line_items(work_order_id))
    if day["status"] in ("FULL", "CLOSED"):
        raise err(errors.ERR_CAPACITY_EXCEEDED, "ShopDay is FULL or CLOSED")
    if day["booked_hours"] + order_hours > day["labor_capacity_hours"]:
        raise err(errors.ERR_CAPACITY_EXCEEDED,
                  "PRODUCTION booking would exceed labor capacity")

    rec = base_record(common=True)
    rec.update({
        "work_order_id": work_order_id,
        "shop_day_id": shop_day_id,
        "kind": "PRODUCTION",
        "scheduled_window_start": None,
        "scheduled_window_end": None,
        "status": "PLANNED",
        "_booked_hours": order_hours,
    })
    db.fulfillment_legs[rec["id"]] = rec

    day["booked_hours"] = day["booked_hours"] + order_hours
    touch(day)
    recompute_shop_day_status(day)

    wo["status"] = "IN_PRODUCTION"
    touch(wo)
    return ok_object(serialize(rec), 201)


def _create_logistics_leg(work_order_id, kind, window_start, window_end):
    if window_start is not None and not isinstance(window_start, str):
        raise err(errors.ERR_INVALID_REQUEST, "scheduled_window_start must be a string")
    if window_end is not None and not isinstance(window_end, str):
        raise err(errors.ERR_INVALID_REQUEST, "scheduled_window_end must be a string")
    if not window_start or not window_end:
        raise err(errors.ERR_INVALID_REQUEST,
                  "PICKUP/DELIVERY legs require scheduled_window_start and end")
    # Window validity (priority 32): end strictly after start.
    if not (window_end > window_start):
        raise err(errors.ERR_INVALID_WINDOW, "Window end must be after start")

    # Delivery conflict (priority 41): half-open overlap with non-CANCELLED DELIVERY.
    if kind == "DELIVERY":
        for fl in db.fulfillment_legs.values():
            if fl["kind"] == "DELIVERY" and fl["status"] != "CANCELLED":
                ex_start = fl["scheduled_window_start"]
                ex_end = fl["scheduled_window_end"]
                if ex_start < window_end and window_start < ex_end:
                    raise err(errors.ERR_DELIVERY_WINDOW_CONFLICT,
                              "Delivery window conflicts with an existing leg")

    rec = base_record(common=True)
    rec.update({
        "work_order_id": work_order_id,
        "shop_day_id": None,
        "kind": kind,
        "scheduled_window_start": window_start,
        "scheduled_window_end": window_end,
        "status": "PLANNED",
        "_booked_hours": 0,
    })
    db.fulfillment_legs[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/fulfillment-legs/<fid>")
def get_fulfillment_leg(fid):
    _, role = get_identity()
    require_roles(role, {"ShopManager", "Estimator", "Customer"})
    rec = get_resource_or_404(db.fulfillment_legs, fid)
    return ok_object(serialize(rec), 200)


@bp.get("/fulfillment-legs")
def list_fulfillment_legs():
    _, role = get_identity()
    require_roles(role, {"ShopManager", "Estimator", "Customer"})
    limit, offset = parse_pagination()
    work_order_id = request.args.get("work_order_id")
    shop_day_id = request.args.get("shop_day_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    matches = list(db.fulfillment_legs.values())
    if work_order_id is not None:
        matches = [f for f in matches if f["work_order_id"] == work_order_id]
    if shop_day_id is not None:
        matches = [f for f in matches if f.get("shop_day_id") == shop_day_id]
    if kind is not None:
        matches = [f for f in matches if f["kind"] == kind]
    if status is not None:
        matches = [f for f in matches if f["status"] == status]
    page, total = paginate(matches, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/fulfillment-legs/<fid>/dispatch")
def dispatch_leg(fid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    rec = get_resource_or_404(db.fulfillment_legs, fid)
    if rec["status"] != "PLANNED":
        raise err(errors.ERR_INVALID_STATE, "Leg must be PLANNED to dispatch")
    # PICKUP/DELIVERY: window present and end > start.
    if rec["kind"] in ("PICKUP", "DELIVERY"):
        ws = rec.get("scheduled_window_start")
        we = rec.get("scheduled_window_end")
        if not ws or not we or not (we > ws):
            raise err(errors.ERR_INVALID_WINDOW,
                      "PICKUP/DELIVERY dispatch requires a valid window")
    rec["status"] = "DISPATCHED"
    touch(rec)
    return ok_object(serialize(rec), 200)


@bp.post("/fulfillment-legs/<fid>/complete")
def complete_leg(fid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    rec = get_resource_or_404(db.fulfillment_legs, fid)
    if rec["status"] != "DISPATCHED":
        raise err(errors.ERR_INVALID_STATE, "Leg must be DISPATCHED to complete")
    rec["status"] = "COMPLETED"
    touch(rec)
    return ok_object(serialize(rec), 200)


@bp.post("/fulfillment-legs/<fid>/cancel")
def cancel_leg(fid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    rec = get_resource_or_404(db.fulfillment_legs, fid)
    if rec["status"] != "PLANNED":
        raise err(errors.ERR_INVALID_STATE, "Leg must be PLANNED to cancel")
    # PRODUCTION: release booked capacity; FULL->OPEN if applicable.
    if rec["kind"] == "PRODUCTION":
        day = db.shop_days.get(rec.get("shop_day_id"))
        if day is not None:
            day["booked_hours"] = day["booked_hours"] - rec.get("_booked_hours", 0)
            touch(day)
            recompute_shop_day_status(day)
        rec["_booked_hours"] = 0
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(serialize(rec), 200)
