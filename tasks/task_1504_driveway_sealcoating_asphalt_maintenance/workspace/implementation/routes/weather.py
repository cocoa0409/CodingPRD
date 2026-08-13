"""WeatherSnapshot endpoints + cascade."""

from flask import Blueprint, request

from clock import format_iso_ms, now
from db import DB
from middleware import (
    require_role, get_json_body, require_fields, check_unknown_fields,
    require_enum, require_number, paginate, err, touch, valid_date_str, new_id,
)
from response import success_object, success_list
from errors import ERR_INVALID_REQUEST
from services import latest_weather_snapshot, find_displacement_plan_for_work_order

bp = Blueprint("weather", __name__)


def serialize_snapshot(s):
    return {
        "id": s["id"],
        "target_date": s["target_date"],
        "min_temp_f": s["min_temp_f"],
        "max_temp_f": s["max_temp_f"],
        "precip_probability_pct": s["precip_probability_pct"],
        "precipitation_mm": s["precipitation_mm"],
        "source": s["source"],
        "created_at": s["created_at"],
    }


@bp.post("/api/weather-snapshots")
def create_snapshot():
    require_role("OfficeAdmin", "Dispatcher")
    body = get_json_body()
    check_unknown_fields(body, {"target_date", "min_temp_f", "max_temp_f",
                                 "precip_probability_pct", "precipitation_mm", "source"})
    require_fields(body, ["target_date", "min_temp_f", "max_temp_f",
                          "precip_probability_pct", "precipitation_mm", "source"])
    target_date = body["target_date"]
    if not valid_date_str(target_date):
        raise err(ERR_INVALID_REQUEST, 400, "target_date must be YYYY-MM-DD")
    min_temp = require_number(body, "min_temp_f")
    max_temp = require_number(body, "max_temp_f")
    precip_prob = require_number(body, "precip_probability_pct", ge=0, integer=True)
    if precip_prob > 100:
        raise err(ERR_INVALID_REQUEST, 400, "precip_probability_pct must be 0-100")
    precip_mm = require_number(body, "precipitation_mm", ge=0)
    source = require_enum(body, "source", {"FORECAST", "OBSERVED"})
    s = {
        "id": new_id(),
        "created_at": format_iso_ms(now()),
        "target_date": target_date,
        "min_temp_f": min_temp,
        "max_temp_f": max_temp,
        "precip_probability_pct": precip_prob,
        "precipitation_mm": precip_mm,
        "source": source,
    }
    DB.weather_snapshots[s["id"]] = s

    # Cascade: if this snapshot is the latest for target_date and it fails SHEET_HOLD
    # thresholds (precip_probability > 60 OR min_temp < 40), then PUBLISHED sheets
    # on that date -> WEATHER_HOLD; their SCHEDULED WOs -> WEATHER_HOLD; their
    # NOTICE_SENT/CLEARED displacement plans -> STALE.
    latest = latest_weather_snapshot(target_date)
    if latest is not None and latest["id"] == s["id"]:
        fails = precip_prob > 60 or min_temp < 40
        if fails:
            for sheet in DB.route_sheets.values():
                if sheet["service_date"] == target_date and sheet["status"] == "PUBLISHED":
                    sheet["status"] = "WEATHER_HOLD"
                    touch(sheet)
                    for wo in DB.work_orders.values():
                        if wo["route_sheet_id"] == sheet["id"] and wo["execution_status"] == "SCHEDULED":
                            wo["execution_status"] = "WEATHER_HOLD"
                            touch(wo)
                            plan = find_displacement_plan_for_work_order(wo["id"])
                            if plan is not None and plan["status"] in ("NOTICE_SENT", "CLEARED"):
                                plan["status"] = "STALE"
                                touch(plan)
    return success_object(serialize_snapshot(s), status=201)


@bp.get("/api/weather-snapshots")
def list_snapshots():
    require_role("OfficeAdmin", "Dispatcher", "CrewLead")
    target_filter = request.args.get("target_date")
    items = list(DB.weather_snapshots.values())
    if target_filter:
        items = [s for s in items if s["target_date"] == target_filter]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_snapshot(s) for s in page], limit, offset, total)
