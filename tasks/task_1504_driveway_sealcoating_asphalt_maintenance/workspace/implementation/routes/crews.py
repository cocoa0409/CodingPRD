"""Crew endpoints + utilization."""

from flask import Blueprint, request
from decimal import Decimal

from db import DB
from middleware import (
    require_role, get_json_body, require_fields, check_unknown_fields,
    require_number, require_bool, base_fields, paginate, err,
    round_half_up_1dp,
)
from response import success_object, success_list
from errors import ERR_CREW_NOT_FOUND, ERR_INVALID_REQUEST

bp = Blueprint("crews", __name__)


def serialize_crew(c):
    return {
        "id": c["id"],
        "crew_name": c["crew_name"],
        "home_zone": c["home_zone"],
        "daily_capacity_sqft": c["daily_capacity_sqft"],
        "active": c["active"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.post("/api/crews")
def create_crew():
    require_role("OfficeAdmin")
    body = get_json_body()
    check_unknown_fields(body, {"crew_name", "home_zone", "daily_capacity_sqft", "active"})
    require_fields(body, ["crew_name", "home_zone", "daily_capacity_sqft"])
    capacity = require_number(body, "daily_capacity_sqft", gt=0, integer=True)
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise err(ERR_INVALID_REQUEST, 400, "active must be a boolean")
    c = base_fields()
    c.update({
        "crew_name": body["crew_name"],
        "home_zone": body["home_zone"],
        "daily_capacity_sqft": capacity,
        "active": active,
    })
    DB.crews[c["id"]] = c
    return success_object(serialize_crew(c), status=201)


@bp.get("/api/crews")
def list_crews():
    require_role("OfficeAdmin", "Dispatcher")
    items = sorted(DB.crews.values(), key=lambda c: c["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_crew(c) for c in page], limit, offset, total)


@bp.get("/api/crews/<crewId>")
def get_crew(crewId):
    require_role("OfficeAdmin", "Dispatcher")
    c = DB.crews.get(crewId)
    if c is None:
        raise err(ERR_CREW_NOT_FOUND, 404, "Crew id does not exist")
    return success_object(serialize_crew(c))


@bp.get("/api/crews/<crewId>/utilization")
def crew_utilization(crewId):
    require_role("OfficeAdmin", "Dispatcher")
    c = DB.crews.get(crewId)
    if c is None:
        raise err(ERR_CREW_NOT_FOUND, 404, "Crew id does not exist")
    month = request.args.get("month")
    if not month or not isinstance(month, str) or len(month) != 7 or month[4] != "-":
        raise err(ERR_INVALID_REQUEST, 400, "month must be YYYY-MM")
    # Sheets in scope
    sheets = [s for s in DB.route_sheets.values()
              if s["crew_id"] == crewId
              and s["service_date"].startswith(month)
              and s["status"] != "CANCELLED"]
    capacity = sum(s["capacity_sqft"] for s in sheets)
    projected_statuses = {"SCHEDULED", "WEATHER_HOLD", "IN_PROGRESS", "CURING", "COMPLETED"}
    realized_statuses = {"COMPLETED", "CLOSED"}
    sheet_ids = {s["id"] for s in sheets}
    projected = 0
    realized = 0
    for wo in DB.work_orders.values():
        if wo["route_sheet_id"] in sheet_ids:
            if wo["execution_status"] in projected_statuses and wo["quoted_area_sqft"] is not None:
                projected += wo["quoted_area_sqft"]
            if wo["execution_status"] in realized_statuses and wo["actual_area_sqft"] is not None:
                realized += wo["actual_area_sqft"]
    if capacity == 0:
        proj_pct = 0.0
        real_pct = 0.0
    else:
        proj_pct = round_half_up_1dp(Decimal(str(projected)) / Decimal(str(capacity)) * Decimal(100))
        real_pct = round_half_up_1dp(Decimal(str(realized)) / Decimal(str(capacity)) * Decimal(100))
    return success_object({
        "month": month,
        "capacity_sqft": capacity,
        "projected_sqft": projected,
        "realized_sqft": realized,
        "projected_utilization_pct": proj_pct,
        "realized_utilization_pct": real_pct,
    })
