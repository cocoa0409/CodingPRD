from flask import Blueprint

import db
import core
import ser
import find
from core import ApiError

bp = Blueprint("routes", __name__)


@bp.post("/routes")
@core.require_auth(["RouteManager"])
def create_route():
    body = core.get_body()
    name = core.require_field(body, "name", "str")
    zone = core.require_field(body, "zone", "str")
    service_days = core.require_field(body, "service_days", "list")
    max_meals = core.require_field(body, "max_meals_per_run", "int")

    if len(service_days) == 0:
        core.invalid_value("service_days must be non-empty")
    for day in service_days:
        if day not in core.WEEKDAY_SET:
            core.invalid_value("service_days contains an invalid weekday")
    if max_meals < 1:
        core.invalid_value("max_meals_per_run must be >= 1")

    rec = db.base_record()
    rec.update({
        "name": name,
        "zone": zone,
        "service_days": service_days,
        "driver_id": None,
        "max_meals_per_run": max_meals,
        "status": "DRAFT",
    })
    db.routes[rec["id"]] = rec
    return core.ok_object(ser.route(rec), 201)


@bp.get("/routes/<rid>")
@core.require_auth(core.ALL_ROLES)
def get_route(rid):
    r = find.route(rid)
    return core.ok_object(ser.route(r))


@bp.get("/routes")
@core.require_auth(core.ALL_ROLES)
def list_routes():
    args = core.request.args
    items = list(db.routes.values())
    for key in ("driver_id", "zone", "status"):
        val = args.get(key)
        if val is not None:
            items = [r for r in items if r[key] == val]
    items = ser.sorted_by_seq(items)
    limit, offset = core.get_pagination()
    page, total = core.paginate(items, limit, offset)
    return core.ok_array([ser.route(r) for r in page], limit, offset, total)


@bp.post("/routes/<rid>/assign-driver")
@core.require_auth(["RouteManager"])
def assign_driver(rid):
    body = core.get_body()
    driver_id = core.require_field(body, "driver_id", "str")
    route = find.route(rid)
    find.driver(driver_id)

    this_days = set(route["service_days"])
    for other in db.routes.values():
        if other["id"] == rid:
            continue
        if other["driver_id"] != driver_id:
            continue
        if other["status"] not in ("DRAFT", "ACTIVE"):
            continue
        if this_days & set(other["service_days"]):
            raise ApiError("ERR_DRIVER_DAY_CONFLICT", 409,
                           "driver already assigned to an overlapping route")

    route["driver_id"] = driver_id
    db.touch(route)
    return core.ok_object(ser.route(route))


@bp.post("/routes/<rid>/activate")
@core.require_auth(["RouteManager"])
def activate_route(rid):
    route = find.route(rid)
    if route["driver_id"] is None:
        raise ApiError("ERR_ROUTE_HAS_NO_DRIVER", 409, "route has no assigned driver")
    driver = db.drivers.get(route["driver_id"])
    if driver is None or driver["status"] != "ACTIVE":
        raise ApiError("ERR_DRIVER_NOT_ACTIVE", 409, "assigned driver is not ACTIVE")
    route["status"] = "ACTIVE"
    db.touch(route)
    return core.ok_object(ser.route(route))
