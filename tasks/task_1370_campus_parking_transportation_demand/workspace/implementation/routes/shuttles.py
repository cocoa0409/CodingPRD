"""Shuttle route endpoints."""
import math

from flask import Blueprint, request

import db
from errors import (
    bad_request,
    invalid_interval,
    not_found,
    conflict,
    payment_required,
    unprocessable,
    ERR_FUND_NOT_FOUND,
    ERR_ROUTE_NOT_FOUND,
    ERR_ROUTE_INVALID_STATE,
    ERR_INSUFFICIENT_FUNDING,
    ERR_INSUFFICIENT_SHUTTLE_CAPACITY,
)
from middleware import get_caller, require_roles, ALL_ROLES
from response import success, success_list, parse_pagination
from services.core import (
    new_record,
    serialize,
    touch,
    check_fleet_buffer,
    recompute_fund,
    parse_iso_date,
)

bp = Blueprint("shuttles", __name__)


def _get_route_or_404(route_id: str) -> dict:
    record = db.shuttle_routes.get(route_id)
    if record is None:
        raise not_found(ERR_ROUTE_NOT_FOUND, "No shuttle route with the given id")
    return record


@bp.post("/parking/shuttle-routes")
def create_route():
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    body = request.get_json(silent=True) or {}

    fund_id = body.get("fund_id")
    route_code = body.get("route_code")
    fleet_group = body.get("fleet_group")
    start_min = body.get("service_window_start_minutes")
    end_min = body.get("service_window_end_minutes")
    headway = body.get("headway_minutes")
    vehicle_capacity = body.get("vehicle_capacity")
    projected = body.get("projected_daily_ridership")
    annual_cost = body.get("annual_operating_cost_cents")

    # Existence (priority 4): fund
    if not isinstance(fund_id, str) or not fund_id:
        raise bad_request("fund_id is required")
    fund = db.funds.get(fund_id)
    if fund is None:
        raise not_found(ERR_FUND_NOT_FOUND, "No transportation fund with the given id")

    # Request shape (priority 6)
    if not isinstance(route_code, str) or not route_code:
        raise bad_request("route_code is required")
    if not isinstance(fleet_group, str) or not fleet_group:
        raise bad_request("fleet_group is required")
    if not isinstance(start_min, int) or isinstance(start_min, bool) or not (0 <= start_min <= 1439):
        raise bad_request("service_window_start_minutes must be an integer in 0..1439")
    if not isinstance(end_min, int) or isinstance(end_min, bool):
        raise bad_request("service_window_end_minutes must be an integer")
    if end_min <= start_min:
        raise invalid_interval("service_window_end_minutes must be strictly greater than start")
    if end_min > 1440:
        raise bad_request("service_window_end_minutes must be <= 1440")
    if not isinstance(headway, int) or isinstance(headway, bool) or headway < 1:
        raise bad_request("headway_minutes must be an integer >= 1")
    if not isinstance(vehicle_capacity, int) or isinstance(vehicle_capacity, bool) or vehicle_capacity < 1:
        raise bad_request("vehicle_capacity must be an integer >= 1")
    if not isinstance(projected, int) or isinstance(projected, bool) or projected < 0:
        raise bad_request("projected_daily_ridership must be an integer >= 0")
    if not isinstance(annual_cost, int) or isinstance(annual_cost, bool) or annual_cost < 0:
        raise bad_request("annual_operating_cost_cents must be an integer >= 0")

    # Temporal (priority 9): fleet window buffer vs non-terminal routes in group
    check_fleet_buffer(fleet_group, start_min, end_min, ("PLANNED", "ACTIVE", "SUSPENDED"))

    planned_runs = math.floor((end_min - start_min) / headway)
    daily_capacity = planned_runs * vehicle_capacity

    record = new_record()
    record.update(
        fund_id=fund_id,
        route_code=route_code,
        fleet_group=fleet_group,
        service_window_start_minutes=start_min,
        service_window_end_minutes=end_min,
        headway_minutes=headway,
        vehicle_capacity=vehicle_capacity,
        projected_daily_ridership=projected,
        annual_operating_cost_cents=annual_cost,
        status="PLANNED",
        planned_daily_runs=planned_runs,
        daily_capacity=daily_capacity,
        ridership_total=0,
    )
    db.shuttle_routes[record["id"]] = record
    return success(serialize(record), 201)


@bp.get("/parking/shuttle-routes")
def list_routes():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)

    fund_id = request.args.get("fund_id")
    fleet_group = request.args.get("fleet_group")
    status = request.args.get("status")

    items = list(db.shuttle_routes.values())
    if fund_id is not None:
        items = [r for r in items if r["fund_id"] == fund_id]
    if fleet_group is not None:
        items = [r for r in items if r["fleet_group"] == fleet_group]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/parking/shuttle-routes/<routeId>")
def get_route(routeId):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    record = _get_route_or_404(routeId)
    return success(serialize(record), 200)


@bp.post("/parking/shuttle-routes/<routeId>/activate")
def activate_route(routeId):
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    route = _get_route_or_404(routeId)

    # State (priority 7)
    if route["status"] not in ("PLANNED", "SUSPENDED"):
        raise conflict(ERR_ROUTE_INVALID_STATE, "Activate requires status PLANNED or SUSPENDED")

    # Temporal (priority 9): fleet buffer re-check vs ACTIVE routes in group
    check_fleet_buffer(
        route["fleet_group"],
        route["service_window_start_minutes"],
        route["service_window_end_minutes"],
        ("ACTIVE",),
        exclude_route_id=route["id"],
    )

    # Fiscal (priority 12): seat coverage before funding
    if route["daily_capacity"] < route["projected_daily_ridership"]:
        raise unprocessable(
            ERR_INSUFFICIENT_SHUTTLE_CAPACITY,
            "daily_capacity < projected_daily_ridership",
        )
    fund = db.funds[route["fund_id"]]
    recompute_fund(fund)
    if fund["available_balance_cents"] < route["annual_operating_cost_cents"]:
        raise payment_required(
            ERR_INSUFFICIENT_FUNDING,
            "fund.available_balance_cents < annual_operating_cost_cents",
        )

    first_activation = route["status"] == "PLANNED"
    route["status"] = "ACTIVE"
    touch(route)

    # committed_shuttle_funding_cents is derived from routes in ACTIVE/SUSPENDED
    recompute_fund(fund)
    touch(fund)

    return success(serialize(route), 200)


@bp.post("/parking/shuttle-routes/<routeId>/suspend")
def suspend_route(routeId):
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    route = _get_route_or_404(routeId)

    if route["status"] != "ACTIVE":
        raise conflict(ERR_ROUTE_INVALID_STATE, "Suspend requires status ACTIVE")

    route["status"] = "SUSPENDED"
    touch(route)
    fund = db.funds[route["fund_id"]]
    recompute_fund(fund)
    touch(fund)
    return success(serialize(route), 200)


@bp.post("/parking/shuttle-routes/<routeId>/ridership-logs")
def log_ridership(routeId):
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    route = _get_route_or_404(routeId)
    body = request.get_json(silent=True) or {}

    log_date = parse_iso_date(body.get("log_date"), "log_date")
    boardings = body.get("boardings")
    if not isinstance(boardings, int) or isinstance(boardings, bool) or boardings < 0:
        raise bad_request("boardings must be an integer >= 0")

    db.ridership_logs.append(
        {"route_id": route["id"], "log_date": log_date.isoformat(), "boardings": boardings}
    )
    route["ridership_total"] += boardings
    touch(route)
    return success(serialize(route), 201)
