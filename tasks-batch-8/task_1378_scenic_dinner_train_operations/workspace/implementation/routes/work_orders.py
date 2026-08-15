"""Maintenance work orders: schedule with the 60-minute turnaround buffer and
committed-excursion guards; START/COMPLETE keep the unit's status in sync."""
from flask import Blueprint

import db
from auth import require_roles
from db import new_entity, public, touch
from envelope import success_obj
from errors import (
    ApiError,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_STATE,
    ERR_MAINTENANCE_WINDOW_CONFLICT,
    ERR_NOT_FOUND,
    ERR_STOCK_COMMITTED,
    ERR_STOCK_OUT_OF_SERVICE,
    ERR_STOCK_UNAVAILABLE,
    ERR_VALIDATION,
)
from services.core import stock_on_committed_excursion_dates, stock_wo_buffer_conflict
from timeutil import iso_z
from validators import body, req_dt, req_enum, req_str

bp = Blueprint("work_orders", __name__)

SCOPES = ("INSPECTION", "REPAIR", "OVERHAUL")


def get_wo_or_404(wo_id):
    wo = db.work_orders.get(wo_id)
    if wo is None:
        raise ApiError(ERR_NOT_FOUND, "Work order not found", 404)
    return wo


@bp.post("/railroad/work-orders")
def create_work_order():
    require_roles("Mechanic")
    data = body()
    stock_id = req_str(data, "stock_id")
    window_start = req_dt(data, "window_start")
    window_end = req_dt(data, "window_end")
    scope = req_enum(data, "scope", SCOPES)
    if window_end <= window_start:
        raise ApiError(
            ERR_VALIDATION, "window_end must be strictly after window_start", 400
        )
    stock = db.rolling_stock.get(stock_id)
    if stock is not None and stock["status"] == "OUT_OF_SERVICE":
        raise ApiError(
            ERR_STOCK_OUT_OF_SERVICE, "Operation targets a retired stock unit", 409
        )
    if stock is None:
        raise ApiError(ERR_INVALID_REFERENCE, "stock_id does not exist", 422)
    # Temporal tier (9d): turnaround buffer vs other SCHEDULED/IN_PROGRESS WOs.
    if stock_wo_buffer_conflict(stock["id"], window_start, window_end):
        raise ApiError(
            ERR_MAINTENANCE_WINDOW_CONFLICT,
            "Window violates the 60-minute turnaround buffer against another "
            "work order on this unit",
            409,
        )
    # Temporal tier (9e): window vs PUBLISHED/BOARDING excursions using the unit.
    if stock_on_committed_excursion_dates(stock["id"], window_start, window_end):
        raise ApiError(
            ERR_STOCK_COMMITTED,
            "Window intersects the service date of a committed excursion using "
            "this unit",
            409,
        )
    wo = new_entity(
        {
            "stock_id": stock["id"],
            "window_start": iso_z(window_start),
            "window_end": iso_z(window_end),
            "scope": scope,
            "status": "SCHEDULED",
        }
    )
    db.work_orders[wo["id"]] = wo
    return success_obj(public(wo), 201)


@bp.post("/railroad/work-orders/<wid>/events")
def work_order_event(wid):
    require_roles("Mechanic")
    wo = get_wo_or_404(wid)
    data = body()
    event_type = data.get("event_type")
    if event_type == "START":
        if wo["status"] != "SCHEDULED":
            raise ApiError(
                ERR_INVALID_STATE, "Only a SCHEDULED work order can be started", 409
            )
        stock = db.rolling_stock.get(wo["stock_id"])
        if stock is not None and stock["status"] == "IN_MAINTENANCE":
            raise ApiError(
                ERR_STOCK_UNAVAILABLE, "Stock unit is IN_MAINTENANCE", 409
            )
        if stock is not None and stock["status"] == "OUT_OF_SERVICE":
            raise ApiError(
                ERR_STOCK_OUT_OF_SERVICE,
                "Operation targets a retired stock unit",
                409,
            )
        wo["status"] = "IN_PROGRESS"
        touch(wo)
        if stock is not None and stock["status"] != "IN_MAINTENANCE":
            stock["status"] = "IN_MAINTENANCE"
            touch(stock)
    elif event_type == "COMPLETE":
        if wo["status"] != "IN_PROGRESS":
            raise ApiError(
                ERR_INVALID_STATE,
                "Only an IN_PROGRESS work order can be completed",
                409,
            )
        wo["status"] = "COMPLETED"
        touch(wo)
        stock = db.rolling_stock.get(wo["stock_id"])
        if stock is not None and stock["status"] == "IN_MAINTENANCE":
            still_open = any(
                w["stock_id"] == stock["id"] and w["status"] == "IN_PROGRESS"
                for w in db.work_orders.values()
            )
            if not still_open:
                stock["status"] = "AVAILABLE"
                touch(stock)
    else:
        raise ApiError(ERR_VALIDATION, "Unknown event_type: %r" % event_type, 400)
    return success_obj(public(wo), 200)
