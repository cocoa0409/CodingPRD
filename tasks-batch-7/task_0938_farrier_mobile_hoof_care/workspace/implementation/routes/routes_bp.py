"""Routes and stop insertion (PRD 3.4)."""

from flask import Blueprint

from core.auth import authenticate
from core.constants import (
    MAX_STOPS_PER_ROUTE,
    MINUTES_PER_DAY,
    ZONE_TO_TRAVEL_MINUTES,
)
from core.errors import ApiError
from core.store import db, order_key
from core.timeutil import parse_iso_date, weekday_token
from core.validate import body, out_of_range, req_date, req_int, req_str
from domain.gates import gate1_farrier, gate2_route_open
from domain.lookup import guard_route, must, must_ref
from domain.routecalc import (
    check_access_window,
    check_adjacency,
    check_capacity,
    recompute_route_totals,
    stops_of,
)
from domain.routeops import cancel_route

from ._common import listing, single

bp = Blueprint("routes", __name__)

READ_ROLES = ("PlatformAdmin", "Dispatcher", "Farrier")


@bp.post("/routes")
def create_route():
    authenticate(("Dispatcher",))
    data = body()
    must_ref("farriers", data.get("farrier_id"))
    farrier_id = req_str(data, "farrier_id")
    route_date = req_date(data, "route_date")
    farrier = db.get("farriers", farrier_id)
    gate1_farrier(farrier)
    route = db.mint(
        "routes",
        {
            "farrier_id": farrier_id,
            "route_date": route_date,
            "status": "DRAFT",
            "committed_units": 0,
            "committed_minutes": 0,
            "stop_count": 0,
        },
    )
    return single(route, 201)


@bp.get("/routes")
def list_routes():
    return listing(
        "routes",
        {"farrier_id": "farrier_id", "status": "status", "route_date": "route_date"},
        READ_ROLES,
    )


@bp.get("/routes/<route_id>")
def read_route(route_id):
    authenticate(READ_ROLES)
    route = must("routes", route_id)
    guard_route(route)
    return single(route)


@bp.post("/routes/<route_id>/plan")
def plan_route(route_id):
    authenticate(("Dispatcher",))
    route = must("routes", route_id)
    gate1_farrier(db.get("farriers", route["farrier_id"]))
    if route["status"] != "DRAFT" or route["stop_count"] < 1:
        raise ApiError("ERR_INVALID_STATE")
    route["status"] = "PLANNED"
    db.touch(route)
    return single(route)


@bp.post("/routes/<route_id>/dispatch")
def dispatch_route(route_id):
    authenticate(("Dispatcher",))
    route = must("routes", route_id)
    gate1_farrier(db.get("farriers", route["farrier_id"]))
    if route["status"] != "PLANNED" or route["committed_units"] < 1:
        raise ApiError("ERR_INVALID_STATE")
    route["status"] = "DISPATCHED"
    db.touch(route)
    return single(route)


@bp.post("/routes/<route_id>/close")
def close_route(route_id):
    authenticate(("Dispatcher",))
    route = must("routes", route_id)
    if route["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE")
    for stop in stops_of(route):
        if stop["status"] in ("PENDING", "ARRIVED"):
            raise ApiError("ERR_INVALID_STATE")
    route["status"] = "CLOSED"
    db.touch(route)
    return single(route)


@bp.post("/routes/<route_id>/cancel")
def cancel_route_endpoint(route_id):
    authenticate(("Dispatcher",))
    route = must("routes", route_id)
    if route["status"] not in ("DRAFT", "PLANNED"):
        raise ApiError("ERR_INVALID_STATE")
    cancel_route(route)
    return single(route)


@bp.post("/routes/<route_id>/stops")
def insert_stop(route_id):
    authenticate(("Dispatcher",))
    data = body()
    barn = must_ref("barns", data.get("barn_id"))
    route = must("routes", route_id)
    barn_id = req_str(data, "barn_id")
    sequence_index = req_int(data, "sequence_index")
    planned_start_minute = req_int(data, "planned_start_minute")
    barn = db.get("barns", barn_id)

    # rung 23
    if sequence_index < 1 or sequence_index > route["stop_count"] + 1:
        out_of_range("sequence_index must be between 1 and stop_count + 1 inclusive.")
    if route["stop_count"] >= MAX_STOPS_PER_ROUTE:
        out_of_range("A route may not hold more than %d stops." % MAX_STOPS_PER_ROUTE)
    if planned_start_minute < 0 or planned_start_minute >= MINUTES_PER_DAY:
        out_of_range("planned_start_minute must be at least 0 and below %d." % MINUTES_PER_DAY)

    gate1_farrier(db.get("farriers", route["farrier_id"]))
    gate2_route_open(route)

    route_day = parse_iso_date(route["route_date"])
    if weekday_token(route_day) not in barn["served_weekdays"]:
        raise ApiError("ERR_BARN_WEEKDAY_NOT_SERVED")
    if route["route_date"] in (barn.get("blackout_dates") or []):
        raise ApiError("ERR_BARN_BLACKOUT_DATE")

    travel_minutes = ZONE_TO_TRAVEL_MINUTES[barn["zone"]]
    check_access_window(barn, planned_start_minute, 0)

    # Adjudication of friction 5 (first half): inserting at an index already
    # held by another stop SHIFTS the incumbents one place later rather than
    # being the range violation.  Refusing would leave only stop_count + 1 ever
    # acceptable and strand the whole declared range 1..stop_count, so shifting
    # is the reading that keeps the declared behaviour reachable.
    incumbents = [s for s in stops_of(route, include_voided=False) if s["sequence_index"] >= sequence_index]
    overrides = {s["id"]: {"sequence_index": s["sequence_index"] + 1} for s in incumbents}
    extra = {
        "id": "__new__",
        "sequence_index": sequence_index,
        "planned_start_minute": planned_start_minute,
        "service_minutes": 0,
        "travel_minutes": travel_minutes,
    }
    check_adjacency(route, overrides=overrides, extra=extra, focus_ids={"__new__"})

    check_capacity(route, 0, travel_minutes)

    for stop in sorted(incumbents, key=order_key):
        stop["sequence_index"] += 1
        db.touch(stop)
    stop = db.mint(
        "route_stops",
        {
            "route_id": route["id"],
            "barn_id": barn_id,
            "sequence_index": sequence_index,
            "planned_start_minute": planned_start_minute,
            "status": "PENDING",
            "travel_minutes": travel_minutes,
            "service_minutes": 0,
            "end_minute": planned_start_minute,
            "trip_fee_cents": 0,
            "billable_horse_count": 0,
        },
    )
    recompute_route_totals(route)
    db.touch(route)
    return single(stop, 201)
