"""Delivery route endpoints."""
from flask import Blueprint

from core import (
    LOGISTICS_READERS,
    ROLE_DRIVER,
    ROLE_MANAGER,
    ROLE_THERAPIST,
    ApiError,
    authenticate,
    base_row,
    db,
    enum_filter,
    paginate,
    pagination,
    parse_datetime,
    respond,
    sorted_rows,
    str_filter,
    touch,
)
from domain import get_branch, get_route, recompute_route_rollups, route_stops
from serial import route_out
from validate import Field, validate

bp = Blueprint("delivery_routes", __name__)

ROUTE_STATUSES = ("PLANNING", "LOCKED", "DISPATCHED", "COMPLETED")

CREATE_FIELDS = [
    Field("branch_id", "string", required=True, min_len=1),
    Field("service_date", "date", required=True),
    Field("driver_user_id", "string", required=True, min_len=1),
    Field("shift_start_utc", "datetime", required=True),
    Field("shift_end_utc", "datetime", required=True),
]


def _rollups(route):
    """Live roll-ups over the route's stops; nothing is persisted."""
    total = 0
    refills = 0
    planned = 0
    completed = 0
    missed = 0
    cancelled = 0
    for stop in route_stops(route["id"]):
        status = stop["status"]
        if status in ("PLANNED", "COMPLETED", "MISSED"):
            total += stop["liters_committed"]
        if stop["stop_type"] == "PORTABLE_REFILL" and status in (
            "PLANNED",
            "COMPLETED",
        ):
            refills += 1
        if status == "PLANNED":
            planned += 1
        elif status == "COMPLETED":
            completed += 1
        elif status == "MISSED":
            missed += 1
        elif status == "CANCELLED":
            cancelled += 1
    return {
        "total_o2_liters_committed": total,
        "refill_slots_used": refills,
        "planned_stop_count": planned,
        "completed_stop_count": completed,
        "missed_stop_count": missed,
        "cancelled_stop_count": cancelled,
    }


@bp.post("/delivery-routes")
def create_route():
    authenticate((ROLE_MANAGER,))
    data = validate(CREATE_FIELDS)
    branch = get_branch(data["branch_id"])
    start = parse_datetime(data["shift_start_utc"])
    end = parse_datetime(data["shift_end_utc"])
    if end <= start or start.date().isoformat() != data["service_date"]:
        raise ApiError("ERR_INVALID_SHIFT")
    row = base_row()
    row.update(
        {
            "branch_id": branch["id"],
            "service_date": data["service_date"],
            "driver_user_id": data["driver_user_id"],
            "shift_start_utc": start,
            "shift_end_utc": end,
            "status": "PLANNING",
            "total_o2_liters_committed": 0,
            "refill_slots_used": 0,
            "planned_stop_count": 0,
        }
    )
    db.routes[row["id"]] = row
    return respond(route_out(row), 201)


@bp.get("/delivery-routes")
def list_routes():
    authenticate(LOGISTICS_READERS)
    branch_id = str_filter("branch_id")
    status = enum_filter("status", ROUTE_STATUSES)
    service_date = str_filter("service_date")
    limit, offset = pagination()
    rows = sorted_rows(db.routes.values())
    if branch_id is not None:
        rows = [r for r in rows if r["branch_id"] == branch_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if service_date is not None:
        rows = [r for r in rows if r["service_date"] == service_date]
    return paginate(rows, limit, offset, route_out)


@bp.get("/delivery-routes/<route_id>")
def read_route(route_id):
    authenticate(LOGISTICS_READERS)
    return respond(route_out(get_route(route_id)))


@bp.get("/delivery-routes/<route_id>/manifest")
def route_manifest(route_id):
    """Computed read: the litre roll-up plus the per-status stop breakdown."""
    authenticate((ROLE_MANAGER, ROLE_DRIVER, ROLE_THERAPIST))
    route = get_route(route_id)
    branch = db.branches.get(route["branch_id"])
    counts = _rollups(route)
    return respond(
        {
            "route_id": route["id"],
            "status": route["status"],
            "planned_stop_count": counts["planned_stop_count"],
            "completed_stop_count": counts["completed_stop_count"],
            "missed_stop_count": counts["missed_stop_count"],
            "cancelled_stop_count": counts["cancelled_stop_count"],
            "refill_slots_used": counts["refill_slots_used"],
            "refill_capacity_per_day": (
                branch["refill_capacity_per_day"] if branch is not None else 0
            ),
            "total_o2_liters_committed": counts["total_o2_liters_committed"],
        }
    )


@bp.post("/delivery-routes/<route_id>/lock")
def lock_route(route_id):
    authenticate((ROLE_MANAGER,))
    route = get_route(route_id)
    if route["status"] != "PLANNING":
        raise ApiError("ERR_INVALID_STATE")
    counts = _rollups(route)
    if counts["planned_stop_count"] < 1:
        raise ApiError("ERR_ROUTE_HAS_NO_STOPS")
    branch = get_branch(route["branch_id"])
    if counts["refill_slots_used"] > branch["refill_capacity_per_day"]:
        raise ApiError("ERR_REFILL_CAPACITY_EXCEEDED")
    recompute_route_rollups(route)
    route["status"] = "LOCKED"
    touch(route)
    return respond(route_out(route))


@bp.post("/delivery-routes/<route_id>/unlock")
def unlock_route(route_id):
    authenticate((ROLE_MANAGER,))
    route = get_route(route_id)
    if route["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE")
    route["status"] = "PLANNING"
    touch(route)
    return respond(route_out(route))


@bp.post("/delivery-routes/<route_id>/dispatch")
def dispatch_route(route_id):
    authenticate((ROLE_MANAGER,))
    route = get_route(route_id)
    if route["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE")
    route["status"] = "DISPATCHED"
    touch(route)
    return respond(route_out(route))
