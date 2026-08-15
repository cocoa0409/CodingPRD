"""Rolling stock: rostering (Mechanic), shape rules by stock_type, RETIRE event
with its work-order and DRAFT-consist cascades, per-unit work-order listing."""
from flask import Blueprint

import db
from auth import ALL_ROLES, require_roles
from db import new_entity, public
from envelope import success_list, success_obj
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_STOCK_COMMITTED,
    ERR_VALIDATION,
)
from services.core import retire_stock, stock_on_published_or_boarding
from validators import body, paginate, pagination, req_enum, req_int, req_str

bp = Blueprint("rolling_stock", __name__)

STOCK_TYPES = ("LOCOMOTIVE", "COACH_CAR", "FIRST_CLASS_CAR", "DINING_CAR")


def get_stock_or_404(stock_id):
    stock = db.rolling_stock.get(stock_id)
    if stock is None:
        raise ApiError(ERR_NOT_FOUND, "Rolling stock not found", 404)
    return stock


@bp.post("/railroad/rolling-stock")
def create_stock():
    require_roles("Mechanic")
    data = body()
    unit_code = req_str(data, "unit_code")
    stock_type = req_enum(data, "stock_type", STOCK_TYPES)
    seat_capacity = req_int(data, "seat_capacity")
    table_count = req_int(data, "table_count")
    for existing in db.rolling_stock.values():
        if existing["unit_code"] == unit_code:
            raise ApiError(
                ERR_VALIDATION, "unit_code must be unique across rolling stock", 400
            )
    # Capacity/table shape by stock_type (tier 8g conditional fields).
    if stock_type == "LOCOMOTIVE":
        ok = seat_capacity == 0 and table_count == 0
    elif stock_type == "DINING_CAR":
        ok = seat_capacity > 0 and table_count > 0
    else:  # COACH_CAR / FIRST_CLASS_CAR
        ok = seat_capacity > 0 and table_count == 0
    if not ok:
        raise ApiError(
            ERR_VALIDATION,
            "seat_capacity/table_count shape violates the stock_type rules",
            400,
        )
    stock = new_entity(
        {
            "unit_code": unit_code,
            "stock_type": stock_type,
            "seat_capacity": seat_capacity,
            "table_count": table_count,
            "status": "AVAILABLE",
        }
    )
    db.rolling_stock[stock["id"]] = stock
    return success_obj(public(stock), 201)


@bp.get("/railroad/rolling-stock/<sid>")
def get_stock(sid):
    require_roles(*ALL_ROLES)
    return success_obj(public(get_stock_or_404(sid)), 200)


@bp.get("/railroad/rolling-stock/<sid>/work-orders")
def list_stock_work_orders(sid):
    require_roles(*ALL_ROLES)
    stock = get_stock_or_404(sid)
    items = [w for w in db.work_orders.values() if w["stock_id"] == stock["id"]]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([public(w) for w in page], limit, offset, total)


@bp.post("/railroad/rolling-stock/<sid>/events")
def stock_event(sid):
    require_roles("Mechanic")
    stock = get_stock_or_404(sid)
    data = body()
    event_type = data.get("event_type")
    if event_type != "RETIRE":
        raise ApiError(ERR_VALIDATION, "Unknown event_type: %r" % event_type, 400)
    if stock["status"] == "OUT_OF_SERVICE":
        raise ApiError(ERR_INVALID_STATE, "Stock unit is already retired", 409)
    in_progress = any(
        w["stock_id"] == stock["id"] and w["status"] == "IN_PROGRESS"
        for w in db.work_orders.values()
    )
    if in_progress:
        raise ApiError(
            ERR_INVALID_STATE,
            "Cannot retire a unit with an IN_PROGRESS work order",
            409,
        )
    if stock_on_published_or_boarding(stock["id"]):
        raise ApiError(
            ERR_STOCK_COMMITTED,
            "Unit is on the consist of a PUBLISHED or BOARDING excursion",
            409,
        )
    retire_stock(stock)
    return success_obj(public(stock), 200)
