"""MaintenanceWindow endpoints: create, list, get, activate, complete, cancel."""
from flask import Blueprint

import db
from db import store, new_id, new_common, touch, iso_out
from errors import ApiError
from response import ok, created, list_ok, filter_eq
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity, resolve_fk
from services import ledger, ordering

bp = Blueprint("windows", __name__)

READ_ROLES = ["DistrictAdmin", "WaterUser", "DitchRider"]

_CREATE_SCHEMA = {
    "canal_reach_id": ("string", True, None, None),
    "start_at": ("datetime", True, None, None),
    "end_at": ("datetime", True, None, None),
    "reason": ("string", False, None, None),
}


@bp.post("/district/maintenance-windows")
def create_window():
    uid, role = get_context()
    body = parse_body(_CREATE_SCHEMA, allow_empty=False)
    start, end = body["_start_at_dt"], body["_end_at_dt"]
    if not end > start:
        raise ApiError("ERR_INVALID_REQUEST", 400, "end_at must be strictly after start_at")
    require_roles(["DistrictAdmin"])
    reach = resolve_fk(store.canal_reaches, body["canal_reach_id"], "canal_reach_id")
    # Half-open overlap vs PLANNED/ACTIVE windows on the same reach; adjacency allowed.
    for w in store.maintenance_windows.values():
        if w["canal_reach_id"] != reach["id"] or w["status"] not in ("PLANNED", "ACTIVE"):
            continue
        if ordering.intervals_overlap(start, end, w["_start_dt"], w["_end_dt"]):
            raise ApiError("ERR_WINDOW_OVERLAP", 422,
                           "Window overlaps an existing PLANNED/ACTIVE window on the reach")
    window = new_common({
        "id": new_id(),
        "canal_reach_id": reach["id"],
        "start_at": iso_out(start),
        "end_at": iso_out(end),
        "_start_dt": start,
        "_end_dt": end,
        "reason": body.get("reason"),
        "status": "PLANNED",
    })
    store.maintenance_windows[window["id"]] = window
    return created(window)


@bp.get("/district/maintenance-windows")
def list_windows():
    uid, role = get_context()
    require_roles(READ_ROLES)
    rows = list(store.maintenance_windows.values())
    for f in ("canal_reach_id", "status"):
        rows = filter_eq(rows, f)
    return list_ok(rows)


@bp.get("/district/maintenance-windows/<wid>")
def get_window(wid):
    uid, role = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.maintenance_windows, wid))


@bp.post("/district/maintenance-windows/<wid>/activate")
def activate_window(wid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    window = require_path_entity(store.maintenance_windows, wid)
    if window["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_WINDOW_STATE", 409,
                       "Only a PLANNED window may be activated")
    now = db.LOGICAL_CLOCK
    if not (window["_start_dt"] <= now < window["_end_dt"]):
        raise ApiError("ERR_WINDOW_OUT_OF_PERIOD", 422,
                       "Logical clock is outside the window's [start_at, end_at) period")
    window["status"] = "ACTIVE"
    touch(window)
    reach = store.canal_reaches[window["canal_reach_id"]]
    reach["status"] = "SHUTDOWN"
    touch(reach)
    # Cascade: cancel every overlapping SCHEDULED order on this reach (releasing
    # committed water) and each such order's non-terminal rider work order.
    affected_allocs = set()
    victims = sorted(
        (o for o in store.turnout_orders.values()
         if o["status"] == "SCHEDULED"
         and o["canal_reach_id"] == reach["id"]
         and ordering.intervals_overlap(o["_start_dt"], o["_end_dt"],
                                        window["_start_dt"], window["_end_dt"])),
        key=lambda r: (r["created_at"], r["_seq"]))
    for o in victims:
        ordering.cascade_cancel_order(o)
        affected_allocs.add(o["season_allocation_id"])
    for alloc_id in affected_allocs:
        ledger.refresh_allocation(store.allocations[alloc_id])
    return ok(window)


@bp.post("/district/maintenance-windows/<wid>/complete")
def complete_window(wid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    window = require_path_entity(store.maintenance_windows, wid)
    if window["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_WINDOW_STATE", 409,
                       "Only an ACTIVE window may be completed")
    window["status"] = "COMPLETED"
    touch(window)
    reach = store.canal_reaches[window["canal_reach_id"]]
    still_active = any(w["canal_reach_id"] == reach["id"] and w["status"] == "ACTIVE"
                       and w["id"] != window["id"]
                       for w in store.maintenance_windows.values())
    if not still_active:
        reach["status"] = "IN_SERVICE"
        touch(reach)
    return ok(window)


@bp.post("/district/maintenance-windows/<wid>/cancel")
def cancel_window(wid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    window = require_path_entity(store.maintenance_windows, wid)
    if window["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_WINDOW_STATE", 409,
                       "Only a PLANNED window may be cancelled")
    window["status"] = "CANCELLED"
    touch(window)
    return ok(window)
