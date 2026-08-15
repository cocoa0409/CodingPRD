"""DeliveryRoute endpoints + availability read (scaffold §1.5, §1.3 route_capacity_consumption)."""
from flask import Blueprint, request
import db
from middleware import get_auth, require_role
from response import success_object, success_list, parse_pagination
from util import get_json_body, req_string, req_int, req_array, stamp_new
from errors import ApiError, ERR_ROUTE_NOT_FOUND, ERR_INVALID_REQUEST
from services import pricing
import clock

bp = Blueprint("routes", __name__)

WEEKDAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}


def view(r):
    return {k: v for k, v in r.items()}


@bp.post("/wholesale/routes")
def create_route():
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["WholesaleAdmin"])
    route_code = req_string(body, "route_code")
    weekdays = req_array(body, "delivery_weekdays")
    for w in weekdays:
        if not isinstance(w, str) or w not in WEEKDAYS:
            raise ApiError(ERR_INVALID_REQUEST, 400, "delivery_weekdays must be weekday enums")
    capacity = req_int(body, "daily_case_capacity")
    if capacity < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "daily_case_capacity must be >= 0")
    min_order = req_int(body, "min_order_cents")
    if min_order < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "min_order_cents must be >= 0")
    r = stamp_new({
        "route_code": route_code,
        "delivery_weekdays": weekdays,
        "daily_case_capacity": capacity,
        "min_order_cents": min_order,
    })
    db.routes[r["id"]] = r
    return success_object(view(r), 201)


@bp.get("/wholesale/routes")
def list_routes():
    get_auth()
    limit, offset = parse_pagination(request.args)
    items = sorted(db.routes.values(), key=lambda r: r["created_at"])
    total = len(items)
    return success_list([view(r) for r in items[offset:offset + limit]], limit, offset, total)


@bp.get("/wholesale/routes/<routeId>")
def get_route(routeId):
    get_auth()
    r = db.routes.get(routeId)
    if r is None:
        raise ApiError(ERR_ROUTE_NOT_FOUND, 404, "DeliveryRoute id does not exist")
    return success_object(view(r))


@bp.get("/wholesale/routes/<routeId>/availability")
def route_availability(routeId):
    get_auth()
    r = db.routes.get(routeId)
    if r is None:
        raise ApiError(ERR_ROUTE_NOT_FOUND, 404, "DeliveryRoute id does not exist")
    date_str = request.args.get("date")
    if date_str is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "date query parameter is required")
    try:
        clock.parse_date(date_str)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "date must be YYYY-MM-DD")
    firm, optimistic = pricing.capacity_consumption(routeId, date_str)
    data = {
        "date": date_str,
        "daily_case_capacity": r["daily_case_capacity"],
        "firm_consumed_cases": firm,
        "optimistic_consumed_cases": optimistic,
        "firm_remaining_cases": r["daily_case_capacity"] - firm,
        "optimistic_remaining_cases": r["daily_case_capacity"] - optimistic,
    }
    return success_object(data)
