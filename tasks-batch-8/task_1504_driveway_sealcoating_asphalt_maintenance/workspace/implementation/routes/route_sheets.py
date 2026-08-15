"""RouteSheet endpoints."""

from flask import Blueprint, request

from db import DB
from middleware import (
    require_role, get_json_body, require_fields, check_unknown_fields,
    require_number, base_fields, paginate, err, touch, valid_date_str,
)
from response import success_object, success_list
from errors import (
    ERR_ROUTE_SHEET_NOT_FOUND, ERR_CREW_NOT_FOUND, ERR_ROUTE_SHEET_NOT_PUBLISHABLE,
    ERR_ROUTE_SHEET_NOT_CANCELLABLE, ERR_INVALID_REQUEST,
)
from services import lazy_route_sheet_completion

bp = Blueprint("route_sheets", __name__)


def serialize_sheet(s):
    return {
        "id": s["id"],
        "crew_id": s["crew_id"],
        "service_date": s["service_date"],
        "capacity_sqft": s["capacity_sqft"],
        "booked_sqft": s["booked_sqft"],
        "total_drive_minutes": s["total_drive_minutes"],
        "open_capacity_sqft": s["open_capacity_sqft"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.post("/api/route-sheets")
def create_route_sheet():
    require_role("Dispatcher")
    body = get_json_body()
    check_unknown_fields(body, {"crew_id", "service_date", "capacity_sqft"})
    require_fields(body, ["crew_id", "service_date"])
    crew = DB.crews.get(body["crew_id"])
    if crew is None:
        raise err(ERR_CREW_NOT_FOUND, 404, "Crew id does not exist")
    service_date = body["service_date"]
    if not valid_date_str(service_date):
        raise err(ERR_INVALID_REQUEST, 400, "service_date must be YYYY-MM-DD")
    capacity = body.get("capacity_sqft")
    if capacity is None:
        capacity = crew["daily_capacity_sqft"]
    else:
        capacity = require_number(body, "capacity_sqft", integer=True)
        if capacity is None or capacity <= 0:
            raise err(ERR_INVALID_REQUEST, 400, "capacity_sqft must be > 0")
    s = base_fields()
    s.update({
        "crew_id": crew["id"],
        "service_date": service_date,
        "capacity_sqft": capacity,
        "booked_sqft": 0,
        "total_drive_minutes": 0,
        "open_capacity_sqft": capacity,
        "status": "OPEN",
    })
    DB.route_sheets[s["id"]] = s
    return success_object(serialize_sheet(s), status=201)


@bp.get("/api/route-sheets")
def list_route_sheets():
    require_role("OfficeAdmin", "Dispatcher", "CrewLead")
    crew_filter = request.args.get("crew_id")
    date_filter = request.args.get("service_date")
    status_filter = request.args.get("status")
    items = list(DB.route_sheets.values())
    for s in items:
        lazy_route_sheet_completion(s)
    if crew_filter:
        items = [s for s in items if s["crew_id"] == crew_filter]
    if date_filter:
        items = [s for s in items if s["service_date"] == date_filter]
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_sheet(s) for s in page], limit, offset, total)


@bp.get("/api/route-sheets/<routeSheetId>")
def get_route_sheet(routeSheetId):
    require_role("OfficeAdmin", "Dispatcher", "CrewLead")
    s = DB.route_sheets.get(routeSheetId)
    if s is None:
        raise err(ERR_ROUTE_SHEET_NOT_FOUND, 404, "Route sheet id does not exist")
    lazy_route_sheet_completion(s)
    return success_object(serialize_sheet(s))


@bp.post("/api/route-sheets/<routeSheetId>/publish")
def publish_route_sheet(routeSheetId):
    require_role("Dispatcher")
    s = DB.route_sheets.get(routeSheetId)
    if s is None:
        raise err(ERR_ROUTE_SHEET_NOT_FOUND, 404, "Route sheet id does not exist")
    lazy_route_sheet_completion(s)
    if s["status"] not in ("OPEN", "WEATHER_HOLD"):
        raise err(ERR_ROUTE_SHEET_NOT_PUBLISHABLE, 409, "publish requires OPEN or WEATHER_HOLD")
    s["status"] = "PUBLISHED"
    touch(s)
    return success_object(serialize_sheet(s))


@bp.post("/api/route-sheets/<routeSheetId>/cancel")
def cancel_route_sheet(routeSheetId):
    require_role("Dispatcher")
    s = DB.route_sheets.get(routeSheetId)
    if s is None:
        raise err(ERR_ROUTE_SHEET_NOT_FOUND, 404, "Route sheet id does not exist")
    lazy_route_sheet_completion(s)
    if s["status"] not in ("OPEN", "PUBLISHED", "WEATHER_HOLD"):
        raise err(ERR_ROUTE_SHEET_NOT_CANCELLABLE, 409,
                  "cancel requires OPEN/PUBLISHED/WEATHER_HOLD with no non-terminal work orders")
    active_statuses = {"SCHEDULED", "WEATHER_HOLD", "IN_PROGRESS", "CURING"}
    has_active = any(
        wo["route_sheet_id"] == s["id"] and wo["execution_status"] in active_statuses
        for wo in DB.work_orders.values()
    )
    if has_active:
        raise err(ERR_ROUTE_SHEET_NOT_CANCELLABLE, 409,
                  "cancel requires no non-terminal work orders")
    s["status"] = "CANCELLED"
    touch(s)
    return success_object(serialize_sheet(s))
