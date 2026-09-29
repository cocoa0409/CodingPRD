"""Replenishment orders (PRD §3.4) and the shop schedule (PRD §3.2)."""

from flask import Blueprint

import calc
from core import (
    ALL_ROLES, D, apply_filters, auth, bump, fail, must_exist, new_row, out,
    page, respond, db,
)
import validate as v

bp = Blueprint("orders", __name__)

READ_ROLES = ALL_ROLES
ORDER_STATUSES = ("UNSCHEDULED", "SCHEDULED", "DELIVERED", "CANCELLED")
TEMPERATURE_MODES = ("DRY", "REFRIGERATED")


# ===========================================================================
# Replenishment orders
# ===========================================================================
@bp.post("/replenishment-orders")
def create_order():
    auth(["FleetPlanner"])
    data = v.body()
    store = v.fk(data, "store_id", "stores")
    store_id = v.rref(data, "store_id")
    cases = v.rint(data, "cases", 1)
    weight_lbs = v.rint(data, "weight_lbs", 0)
    window_start = v.rinstant(data, "requested_window_start")
    window_end = v.rinstant(data, "requested_window_end")
    v.window_order(window_start, window_end, "requested_window_start", "requested_window_end")
    temperature_mode = v.renum(data, "temperature_mode", TEMPERATURE_MODES)
    priority = v.oint(data, "priority", 3, 1, 5)
    if store["status"] != "ACTIVE":
        fail("ERR_STORE_SUSPENDED")
    row = new_row({
        "store_id": store_id,
        "cases": cases,
        "weight_lbs": weight_lbs,
        "requested_window_start": window_start,
        "requested_window_end": window_end,
        "temperature_mode": temperature_mode,
        "priority": priority,
        "status": "UNSCHEDULED",
    })
    db.orders[row["id"]] = row
    return respond(out(row), 201)


@bp.get("/replenishment-orders/<order_id>")
def get_order(order_id):
    auth(READ_ROLES)
    return respond(out(must_exist("orders", order_id)))


@bp.get("/replenishment-orders")
def list_orders():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(list(db.orders.values()), [
        ("store_id", v.qstr("store_id")),
        ("status", v.qenum("status", ORDER_STATUSES)),
        ("temperature_mode", v.qenum("temperature_mode", TEMPERATURE_MODES)),
    ])
    return page(rows, limit, offset)


@bp.post("/replenishment-orders/<order_id>/cancel")
def cancel_order(order_id):
    auth(["FleetPlanner"])
    order = must_exist("orders", order_id)
    data = v.body()
    reason = v.ostr(data, "reason_code")
    if order["status"] != "UNSCHEDULED":
        fail("ERR_ORDER_NOT_SCHEDULABLE")
    order["status"] = "CANCELLED"
    order["_reason_code"] = reason
    bump(order)
    return respond(out(order))


# ===========================================================================
# Maintenance work orders
# ===========================================================================
ASSET_KINDS = ("TRACTOR", "TRAILER")
SERVICE_TYPES = ("PM_A", "PM_B", "INSPECTION", "REPAIR")
WORK_ORDER_STATUSES = ("SCHEDULED", "DEFERRED", "IN_SHOP", "COMPLETED", "CANCELLED")


def _asset_of(work_order):
    if work_order["asset_kind"] == "TRACTOR":
        return "tractor_id", db.tractors.get(work_order.get("tractor_id"))
    return "trailer_id", db.trailers.get(work_order.get("trailer_id"))


@bp.post("/maintenance-work-orders")
def create_work_order():
    auth(["MaintenanceCoordinator"])
    data = v.body()
    v.fk(data, "tractor_id", "tractors")
    v.fk(data, "trailer_id", "trailers")
    asset_kind = v.renum(data, "asset_kind", ASSET_KINDS)
    tractor_id = v.oref(data, "tractor_id")
    trailer_id = v.oref(data, "trailer_id")
    if asset_kind == "TRACTOR":
        if tractor_id is None or trailer_id is not None:
            fail("ERR_INVALID_REQUEST", "asset_kind TRACTOR requires tractor_id and forbids trailer_id.")
        asset_field, asset_id = "tractor_id", tractor_id
    else:
        if trailer_id is None or tractor_id is not None:
            fail("ERR_INVALID_REQUEST", "asset_kind TRAILER requires trailer_id and forbids tractor_id.")
        asset_field, asset_id = "trailer_id", trailer_id
    service_type = v.renum(data, "service_type", SERVICE_TYPES)
    window_start = v.rinstant(data, "window_start_at")
    window_end = v.rinstant(data, "window_end_at")
    v.window_order(window_start, window_end, "window_start_at", "window_end_at")
    calc.check_work_order_conflict(asset_field, asset_id, D(window_start), D(window_end))
    row = new_row({
        "asset_kind": asset_kind,
        "tractor_id": tractor_id,
        "trailer_id": trailer_id,
        "service_type": service_type,
        "window_start_at": window_start,
        "window_end_at": window_end,
        "status": "SCHEDULED",
        "deferral_count": 0,
        "auto_generated": False,
    })
    db.work_orders[row["id"]] = row
    return respond(out(row), 201)


@bp.get("/maintenance-work-orders/<work_order_id>")
def get_work_order(work_order_id):
    auth(READ_ROLES)
    return respond(out(must_exist("work_orders", work_order_id)))


@bp.get("/maintenance-work-orders")
def list_work_orders():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(list(db.work_orders.values()), [
        ("tractor_id", v.qstr("tractor_id")),
        ("trailer_id", v.qstr("trailer_id")),
        ("asset_kind", v.qenum("asset_kind", ASSET_KINDS)),
        ("service_type", v.qenum("service_type", SERVICE_TYPES)),
        ("status", v.qenum("status", WORK_ORDER_STATUSES)),
        ("auto_generated", v.qbool("auto_generated")),
    ])
    return page(rows, limit, offset)


@bp.post("/maintenance-work-orders/<work_order_id>/defer")
def defer_work_order(work_order_id):
    auth(["MaintenanceCoordinator"])
    wo = must_exist("work_orders", work_order_id)
    data = v.body()
    reason = v.ostr(data, "reason_code")
    if wo["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if int(wo["deferral_count"]) >= 2:
        fail("ERR_DEFERRAL_LIMIT")
    wo["status"] = "DEFERRED"
    wo["deferral_count"] = int(wo["deferral_count"]) + 1
    wo["_reason_code"] = reason
    bump(wo)
    return respond(out(wo))


@bp.post("/maintenance-work-orders/<work_order_id>/reschedule")
def reschedule_work_order(work_order_id):
    auth(["MaintenanceCoordinator"])
    wo = must_exist("work_orders", work_order_id)
    data = v.body()
    window_start = v.rinstant(data, "window_start_at")
    window_end = v.rinstant(data, "window_end_at")
    v.window_order(window_start, window_end, "window_start_at", "window_end_at")
    if wo["status"] != "DEFERRED":
        fail("ERR_INVALID_STATE_TRANSITION")
    asset_field = "tractor_id" if wo["asset_kind"] == "TRACTOR" else "trailer_id"
    calc.check_work_order_conflict(
        asset_field, wo.get(asset_field), D(window_start), D(window_end)
    )
    wo["window_start_at"] = window_start
    wo["window_end_at"] = window_end
    wo["status"] = "SCHEDULED"
    bump(wo)
    return respond(out(wo))


@bp.post("/maintenance-work-orders/<work_order_id>/start")
def start_work_order(work_order_id):
    auth(["MaintenanceCoordinator"])
    wo = must_exist("work_orders", work_order_id)
    v.body()
    if wo["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION")
    _, asset = _asset_of(wo)
    if asset is None or asset["status"] != "AVAILABLE":
        fail("ERR_ASSET_NOT_AVAILABLE")
    wo["status"] = "IN_SHOP"
    bump(wo)
    asset["status"] = "IN_SHOP"
    bump(asset)
    return respond(out(wo))


@bp.post("/maintenance-work-orders/<work_order_id>/complete")
def complete_work_order(work_order_id):
    auth(["MaintenanceCoordinator"])
    wo = must_exist("work_orders", work_order_id)
    data = v.body()
    performed = v.oint(data, "performed_odometer_miles", None, 0)
    if wo["status"] != "IN_SHOP":
        fail("ERR_INVALID_STATE_TRANSITION")
    wo["status"] = "COMPLETED"
    wo["_performed_odometer_miles"] = performed
    bump(wo)
    _, asset = _asset_of(wo)
    if asset is not None:
        asset["status"] = "AVAILABLE"
        if (
            wo["asset_kind"] == "TRACTOR"
            and wo["service_type"] in ("PM_A", "PM_B")
        ):
            asset["pm_last_service_odometer"] = asset["odometer_miles"]
            asset["miles_since_pm"] = 0
            asset["pm_hold"] = False
        bump(asset)
    return respond(out(wo))


@bp.post("/maintenance-work-orders/<work_order_id>/cancel")
def cancel_work_order(work_order_id):
    auth(["MaintenanceCoordinator"])
    wo = must_exist("work_orders", work_order_id)
    data = v.body()
    reason = v.ostr(data, "reason_code")
    if wo["status"] != "SCHEDULED" or wo["auto_generated"]:
        fail("ERR_INVALID_STATE_TRANSITION")
    wo["status"] = "CANCELLED"
    wo["_reason_code"] = reason
    bump(wo)
    return respond(out(wo))
