"""CollectionRoute endpoints (PRD §3.4)."""

from flask import Blueprint, request

from db import STORE
from errors import (ApiError, ERR_ROUTE_WINDOW_OVERLAP, ERR_ZONE_NOT_FOUND,
                    err_invalid_request, err_invalid_state, err_not_found)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from services.core import base_record, touch, route_out, parse_date, WEEKDAYS
from services.validate import require_body, check_unknown_fields, req_str, req_int, req_date

bp = Blueprint("routes", __name__)

READ_ROLES = ("ProgramAdmin", "RouteSupervisor", "Resident", "Driver",
              "FieldInspector", "BillingClerk", "OutreachCoordinator")


@bp.post("/routes")
def create_route():
    require_roles("ProgramAdmin")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"zone_id", "weekday", "effective_start_date",
                                "effective_end_date", "max_stops", "max_tonnage_lbs"})
    zone_id = req_str(data, "zone_id")
    weekday = req_str(data, "weekday")
    if weekday not in WEEKDAYS:
        raise err_invalid_request("weekday must be MONDAY..SUNDAY")
    start = req_date(data, "effective_start_date")
    end = req_date(data, "effective_end_date")
    max_stops = req_int(data, "max_stops")
    max_tonnage = req_int(data, "max_tonnage_lbs")

    zone = STORE.zones.get(zone_id)
    if not zone:
        raise err_not_found(ERR_ZONE_NOT_FOUND, "Zone not found")

    # shape: window inside zone season window; end after start
    if parse_date(end) <= parse_date(start):
        raise err_invalid_request("effective_end_date must be after effective_start_date")
    if parse_date(start) < parse_date(zone["season_start_date"]):
        raise err_invalid_request("effective_start_date before zone season_start_date")
    if parse_date(end) > parse_date(zone["season_end_date"]):
        raise err_invalid_request("effective_end_date after zone season_end_date")

    # half-open window overlap with non-ARCHIVED routes for same (zone, weekday)
    for r in STORE.routes.values():
        if r["zone_id"] != zone_id or r["weekday"] != weekday or r["status"] == "ARCHIVED":
            continue
        rs = parse_date(r["effective_start_date"])
        re_ = parse_date(r["effective_end_date"])
        ns = parse_date(start)
        ne = parse_date(end)
        # overlap of [ns, ne) and [rs, re)
        if ns < re_ and rs < ne:
            raise ApiError(ERR_ROUTE_WINDOW_OVERLAP,
                           "Route window overlaps an existing route for this zone/weekday", 409)

    r = base_record()
    r.update({
        "zone_id": zone_id, "weekday": weekday,
        "effective_start_date": start, "effective_end_date": end,
        "max_stops": max_stops, "max_tonnage_lbs": max_tonnage,
        "status": "DRAFT",
    })
    STORE.routes[r["id"]] = r
    return success_object(route_out(r), 201)


@bp.get("/routes")
def list_routes():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.routes.values())
    zid = request.args.get("zone_id")
    wd = request.args.get("weekday")
    st = request.args.get("status")
    if zid is not None:
        items = [r for r in items if r["zone_id"] == zid]
    if wd is not None:
        items = [r for r in items if r["weekday"] == wd]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([route_out(r) for r in page], limit, offset, total)


@bp.get("/routes/<rid>")
def get_route(rid):
    require_roles(*READ_ROLES)
    r = STORE.routes.get(rid)
    if not r:
        raise err_not_found()
    return success_object(route_out(r))


@bp.post("/routes/<rid>/publish")
def publish_route(rid):
    require_roles("ProgramAdmin")
    r = STORE.routes.get(rid)
    if not r:
        raise err_not_found()
    if r["status"] != "DRAFT":
        raise err_invalid_state("Route is not DRAFT")
    r["status"] = "PUBLISHED"
    touch(r)
    return success_object(route_out(r))
