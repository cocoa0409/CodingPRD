"""Service dispatches: booking with half-open van overlap, advance, complete
(with optional order installation), abort (PRD §3.6, §2.9)."""

from flask import Blueprint, request

from db import store, new_entity, touch, pub
from errors import (
    ApiError, ERR_INVALID_WINDOW, ERR_VAN_WINDOW_CONFLICT,
    ERR_CREDIT_HOLD, ERR_INVALID_STATE,
)
from middleware import (
    require_roles, body, get_or_404, get_str, get_dt, present,
)
from response import success, list_response
from services import complete_order

bp = Blueprint("dispatches", __name__)

LIVE_DISPATCH_STATES = ("REQUESTED", "DISPATCHED", "ON_SITE")


@bp.post("/api/service-dispatches")
def create_dispatch():
    require_roles("CounterSales", "ShopManager")
    data = body()
    # existence (priority 3), body FKs left to right
    customer = get_or_404(store.customers, get_str(data, "customer_id"), "customer")
    asset = None
    if present(data, "equipment_asset_id"):
        asset = get_or_404(store.assets, data["equipment_asset_id"], "asset")
    # booking checks in order (PRD §3.6): window shape -> van overlap ->
    # credit hold
    start = get_dt(data, "window_start")
    end = get_dt(data, "window_end")
    if not end > start:
        raise ApiError(ERR_INVALID_WINDOW, 400,
                       "window_end must be strictly after window_start")
    van_id = get_str(data, "van_id")
    # half-open overlap per van over live dispatches only; touching endpoints
    # are allowed
    for other in store.dispatches.values():
        if (other["van_id"] == van_id and other["status"] in LIVE_DISPATCH_STATES
                and start < other["window_end"] and end > other["window_start"]):
            raise ApiError(ERR_VAN_WINDOW_CONFLICT, 409,
                           "Van window overlaps another live dispatch")
    if customer["credit_hold"]:
        raise ApiError(ERR_CREDIT_HOLD, 402, "Customer is on credit hold")
    dispatch = new_entity()
    dispatch.update({
        "customer_id": customer["id"],
        "equipment_asset_id": asset["id"] if asset else None,
        "van_id": van_id,
        "window_start": start,
        "window_end": end,
        "status": "REQUESTED",
        "installed_assembly_order_id": None,
    })
    store.dispatches[dispatch["id"]] = dispatch
    return success(pub(dispatch), status=201)


@bp.get("/api/service-dispatches")
def list_dispatches():
    require_roles("ShopManager", "CounterSales", "FieldTechnician")
    van_id = request.args.get("van_id")
    customer_id = request.args.get("customer_id")
    asset_id = request.args.get("equipment_asset_id")
    installed_order = request.args.get("installed_assembly_order_id")
    status = request.args.get("status")
    items = list(store.dispatches.values())
    if van_id is not None:
        items = [d for d in items if d["van_id"] == van_id]
    if customer_id is not None:
        items = [d for d in items if d["customer_id"] == customer_id]
    if asset_id is not None:
        items = [d for d in items if d["equipment_asset_id"] == asset_id]
    if installed_order is not None:
        items = [d for d in items
                 if d["installed_assembly_order_id"] == installed_order]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return list_response(items)


@bp.get("/api/service-dispatches/<did>")
def get_dispatch(did):
    require_roles("ShopManager", "CounterSales", "FieldTechnician")
    dispatch = get_or_404(store.dispatches, did, "dispatch")
    return success(pub(dispatch), status=200)


@bp.post("/api/service-dispatches/<did>/advance")
def advance_dispatch(did):
    require_roles("FieldTechnician")
    dispatch = get_or_404(store.dispatches, did, "dispatch")
    if dispatch["status"] == "REQUESTED":
        dispatch["status"] = "DISPATCHED"
    elif dispatch["status"] == "DISPATCHED":
        dispatch["status"] = "ON_SITE"
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Dispatch cannot advance from {}".format(dispatch["status"]))
    touch(dispatch)
    return success(pub(dispatch), status=200)


@bp.post("/api/service-dispatches/<did>/complete")
def complete_dispatch(did):
    require_roles("FieldTechnician")
    dispatch = get_or_404(store.dispatches, did, "dispatch")
    data = body()
    # body FK existence (priority 3) before the state rungs
    order = None
    if present(data, "installed_assembly_order_id"):
        order = get_or_404(store.orders, data["installed_assembly_order_id"],
                           "order")
    if dispatch["status"] != "ON_SITE":
        raise ApiError(ERR_INVALID_STATE, 409, "Dispatch is not ON_SITE")
    if order is not None:
        if (order["customer_id"] != dispatch["customer_id"]
                or order["status"] != "TAGGED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "installed order must belong to the dispatch "
                           "customer and be TAGGED")
        # drive the referenced order through TAGGED -> COMPLETED with the
        # full settlement cascade (PRD §3.5)
        complete_order(order)
        dispatch["installed_assembly_order_id"] = order["id"]
    dispatch["status"] = "COMPLETED"
    touch(dispatch)
    return success(pub(dispatch), status=200)


@bp.post("/api/service-dispatches/<did>/abort")
def abort_dispatch(did):
    require_roles("FieldTechnician", "ShopManager")
    dispatch = get_or_404(store.dispatches, did, "dispatch")
    if dispatch["status"] not in ("REQUESTED", "DISPATCHED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Dispatch cannot abort from {}".format(dispatch["status"]))
    # an ABORTED dispatch no longer participates in van overlap checks
    dispatch["status"] = "ABORTED"
    touch(dispatch)
    return success(pub(dispatch), status=200)
