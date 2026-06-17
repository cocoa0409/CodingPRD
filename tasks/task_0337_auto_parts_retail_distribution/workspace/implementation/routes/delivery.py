"""Driver, Bay, and DeliveryRun endpoints (hotshot scheduling)."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    conflict,
    ERR_DUPLICATE_BAY_CODE,
    ERR_DRIVER_WINDOW_CONFLICT,
    ERR_BAY_WINDOW_CONFLICT,
    ERR_RUN_NOT_SCHEDULED,
    ERR_RUN_ORDER_NOT_READY,
    ERR_RUN_NOT_DISPATCHED,
    ERR_RUN_NOT_CANCELLABLE,
    invalid_request,
)
from middleware import require_role, get_body
from response import success, list_success
from services import common as c
from services.model import (
    stamp_common,
    touch,
    serialize,
    get_driver,
    get_bay,
    get_delivery_run,
    get_sales_order,
)

bp = Blueprint("delivery", __name__)

ALL_ROLES = ("CounterClerk", "WholesaleRep", "InventoryManager", "WarrantyAdmin")


# ---- Driver ----
@bp.post("/drivers")
def create_driver():
    require_role("InventoryManager", "CounterClerk", "WholesaleRep")
    body = get_body()
    name = c.as_nonempty_string(body, "name", required=True)
    turnaround_min = c.as_int(body, "turnaround_min", required=False, default=0, min_value=0)
    drv = {"name": name, "turnaround_min": turnaround_min}
    stamp_common(drv)
    db.drivers[drv["id"]] = drv
    return success(serialize(drv), 201)


@bp.get("/drivers")
def list_drivers():
    require_role(*ALL_ROLES)
    limit, offset = c.parse_pagination()
    page, total = c.paginate(db.drivers.values(), limit, offset)
    return list_success([serialize(d) for d in page], limit, offset, total)


@bp.get("/drivers/<did>")
def get_one_driver(did):
    require_role(*ALL_ROLES)
    return success(serialize(get_driver(did)))


# ---- Bay ----
@bp.post("/bays")
def create_bay():
    require_role("InventoryManager", "CounterClerk", "WholesaleRep")
    body = get_body()
    code = c.as_nonempty_string(body, "code", required=True)
    for existing in db.bays.values():
        if existing["code"] == code:
            raise conflict(ERR_DUPLICATE_BAY_CODE)
    bay = {"code": code}
    stamp_common(bay)
    db.bays[bay["id"]] = bay
    return success(serialize(bay), 201)


@bp.get("/bays")
def list_bays():
    require_role(*ALL_ROLES)
    limit, offset = c.parse_pagination()
    page, total = c.paginate(db.bays.values(), limit, offset)
    return list_success([serialize(b) for b in page], limit, offset, total)


@bp.get("/bays/<bid>")
def get_one_bay(bid):
    require_role(*ALL_ROLES)
    return success(serialize(get_bay(bid)))


# ---- DeliveryRun ----
def _driver_conflict(new_start, new_end, turnaround, driver_id) -> bool:
    """Buffered overlap: runs A,B collide when
    A.start < B.end + turnaround AND B.start < A.end + turnaround."""
    for run in db.delivery_runs.values():
        if run["driver_id"] != driver_id:
            continue
        if run["status"] == "CANCELLED":
            continue
        b_start = run["window_start_min"]
        b_end = run["window_end_min"]
        if new_start < b_end + turnaround and b_start < new_end + turnaround:
            return True
    return False


def _bay_conflict(new_start, new_end, bay_id) -> bool:
    """Half-open positive overlap: A.start < B.end AND B.start < A.end.
    Exact adjacency (A.end == B.start) does not conflict."""
    for run in db.delivery_runs.values():
        if run["bay_id"] != bay_id:
            continue
        if run["status"] == "CANCELLED":
            continue
        b_start = run["window_start_min"]
        b_end = run["window_end_min"]
        if new_start < b_end and b_start < new_end:
            return True
    return False


@bp.post("/delivery-runs")
def create_delivery_run():
    require_role("CounterClerk", "WholesaleRep")
    body = get_body()
    order_id = c.as_nonempty_string(body, "order_id", required=True)
    driver_id = c.as_nonempty_string(body, "driver_id", required=True)
    bay_id = c.as_nonempty_string(body, "bay_id", required=True)
    window_start_min = c.as_int(body, "window_start_min", required=True, min_value=0)
    window_end_min = c.as_int(body, "window_end_min", required=True, min_value=0)
    # end must be strictly greater than start
    if window_end_min <= window_start_min:
        raise invalid_request("window_end_min must be greater than window_start_min")

    # existence (body, left-to-right)
    get_sales_order(order_id)
    driver = get_driver(driver_id)
    get_bay(bay_id)

    # priority 17: driver buffered conflict
    if _driver_conflict(window_start_min, window_end_min, driver["turnaround_min"], driver_id):
        raise conflict(ERR_DRIVER_WINDOW_CONFLICT)
    # priority 18: bay half-open conflict
    if _bay_conflict(window_start_min, window_end_min, bay_id):
        raise conflict(ERR_BAY_WINDOW_CONFLICT)

    run = {
        "order_id": order_id,
        "driver_id": driver_id,
        "bay_id": bay_id,
        "window_start_min": window_start_min,
        "window_end_min": window_end_min,
        "status": "SCHEDULED",
    }
    stamp_common(run)
    db.delivery_runs[run["id"]] = run
    return success(serialize(run), 201)


@bp.get("/delivery-runs")
def list_delivery_runs():
    require_role(*ALL_ROLES)
    limit, offset = c.parse_pagination()
    order_id = request.args.get("order_id")
    driver_id = request.args.get("driver_id")
    bay_id = request.args.get("bay_id")
    status = request.args.get("status")
    filters = []
    if order_id is not None:
        filters.append(lambda r: r["order_id"] == order_id)
    if driver_id is not None:
        filters.append(lambda r: r["driver_id"] == driver_id)
    if bay_id is not None:
        filters.append(lambda r: r["bay_id"] == bay_id)
    if status is not None:
        filters.append(lambda r: r["status"] == status)
    page, total = c.paginate(db.delivery_runs.values(), limit, offset, filters)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.get("/delivery-runs/<rid>")
def get_one_delivery_run(rid):
    require_role(*ALL_ROLES)
    return success(serialize(get_delivery_run(rid)))


@bp.post("/delivery-runs/<rid>/dispatch")
def dispatch_run(rid):
    require_role("CounterClerk", "WholesaleRep")
    run = get_delivery_run(rid)
    if run["status"] != "SCHEDULED":
        raise conflict(ERR_RUN_NOT_SCHEDULED)
    order = get_sales_order(run["order_id"])
    if order["fulfillment_status"] not in ("ALLOCATED", "SHIPPED"):
        raise conflict(ERR_RUN_ORDER_NOT_READY)
    run["status"] = "DISPATCHED"
    touch(run)
    return success(serialize(run))


@bp.post("/delivery-runs/<rid>/complete")
def complete_run(rid):
    require_role("CounterClerk", "WholesaleRep")
    run = get_delivery_run(rid)
    if run["status"] != "DISPATCHED":
        raise conflict(ERR_RUN_NOT_DISPATCHED)
    run["status"] = "DELIVERED"
    touch(run)
    return success(serialize(run))


@bp.post("/delivery-runs/<rid>/cancel")
def cancel_run(rid):
    require_role("CounterClerk", "WholesaleRep")
    run = get_delivery_run(rid)
    if run["status"] not in ("SCHEDULED", "DISPATCHED"):
        raise conflict(ERR_RUN_NOT_CANCELLABLE)
    run["status"] = "CANCELLED"
    touch(run)
    return success(serialize(run))
