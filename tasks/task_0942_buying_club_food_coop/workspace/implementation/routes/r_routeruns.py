"""Route runs and pallets (4 + 3 endpoints)."""

from flask import Blueprint

from core import serialize
from core.constants import PALLET_STATUSES, ROLES, ROUTE_RUN_STATUSES, TEMP_CLASSES
from core.envelope import ok, page
from core.errors import ApiError
from core.ladder import (endpoint, enum_filter, free_filter, gate_cycle_closed,
                         pagination, path_row, req_int)
from core.store import DB, touch
from services import consolidation

bp = Blueprint("routeruns", __name__)
R5 = list(ROLES)


@bp.get("/route-runs")
@endpoint(R5)
def list_route_runs(ctx):
    limit, offset = pagination(ctx)
    status = enum_filter(ctx, "status", ROUTE_RUN_STATUSES)
    cycle_id = free_filter(ctx, "cycle_id")
    route_id = free_filter(ctx, "route_id")
    rows = []
    for row in DB.all("RouteRun"):
        if cycle_id is not None and row["cycle_id"] != cycle_id:
            continue
        if route_id is not None and row["route_id"] != route_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/route-runs/<route_run_id>")
@endpoint(R5)
def read_route_run(ctx, route_run_id):
    return ok(serialize.route_run(path_row("route_run_id", route_run_id)))


@bp.post("/route-runs/<route_run_id>/supplier-invoice")
@endpoint(["ClubAdmin", "WarehouseOperator"])
def supplier_invoice(ctx, route_run_id):
    route_run = path_row("route_run_id", route_run_id)     # rung 4
    supplier_invoice_cents = req_int(ctx, "supplier_invoice_cents", minimum=0)   # rung 7
    freight_cents = req_int(ctx, "freight_cents", minimum=0)
    gate_cycle_closed(route_run)                           # rung 9
    if route_run["status"] != "RECEIVED":                  # rung 19
        raise ApiError("ERR_INVALID_ROUTE_RUN_STATE")
    route_run["supplier_invoice_cents"] = supplier_invoice_cents
    route_run["freight_cents"] = freight_cents
    route_run["invoice_recorded_by_user_id"] = ctx.user_id
    touch(route_run)
    consolidation.allocate_freight(route_run)
    return ok(serialize.route_run(route_run))


@bp.post("/route-runs/<route_run_id>/build-pallets")
@endpoint(["ClubAdmin", "WarehouseOperator"])
def build_pallets(ctx, route_run_id):
    route_run = path_row("route_run_id", route_run_id)     # rung 4
    gate_cycle_closed(route_run)                           # rung 9
    if route_run["status"] != "RECEIVED":                  # rung 19
        raise ApiError("ERR_INVALID_ROUTE_RUN_STATE")
    if route_run["supplier_invoice_cents"] <= 0:           # rung 45
        raise ApiError("ERR_SUPPLIER_INVOICE_MISSING")
    consolidation.build_pallets(route_run)                 # rungs 29 and 30 inside
    touch(route_run)
    return ok(serialize.route_run(route_run))


# ---------------------------------------------------------------- pallets ---

@bp.get("/pallets")
@endpoint(R5)
def list_pallets(ctx):
    limit, offset = pagination(ctx)
    temp_class = enum_filter(ctx, "temp_class", TEMP_CLASSES)
    status = enum_filter(ctx, "status", PALLET_STATUSES)
    route_run_id = free_filter(ctx, "route_run_id")
    rows = []
    for row in DB.all("Pallet"):
        if route_run_id is not None and row["route_run_id"] != route_run_id:
            continue
        if temp_class is not None and row["temp_class"] != temp_class:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/pallets/<pallet_id>")
@endpoint(R5)
def read_pallet(ctx, pallet_id):
    return ok(serialize.pallet(path_row("pallet_id", pallet_id)))


@bp.post("/pallets/<pallet_id>/seal")
@endpoint(["ClubAdmin", "WarehouseOperator"])
def seal_pallet(ctx, pallet_id):
    pallet = path_row("pallet_id", pallet_id)              # rung 4
    gate_cycle_closed(pallet)                              # rung 9
    if pallet["status"] != "BUILDING":                     # rung 24
        raise ApiError("ERR_INVALID_PALLET_STATE")
    route_run = DB.get("RouteRun", pallet["route_run_id"])
    cycle = DB.get("Cycle", route_run["cycle_id"]) if route_run else None
    if cycle is None or cycle["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    pallet["status"] = "SEALED"
    touch(pallet)
    return ok(serialize.pallet(pallet))
