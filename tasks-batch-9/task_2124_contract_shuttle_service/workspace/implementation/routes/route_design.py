"""Route endpoints (PRD 3.2): design, publish, republish."""

from flask import Blueprint

import calc
import store
from envelope import created, ok, paginate, pagination
from errors import ApiError
from guards import (ALL_ROLES, authorize, body, equality_filter, id_field,
                    must_exist, validate_body)
from store import touch

bp = Blueprint("route_design", __name__)

CREATE_SPEC = [
    id_field("contract_id"),
    {"name": "name", "kind": "string", "min_len": 1, "max_len": 120},
    {"name": "loop_minutes", "kind": "int", "min": 1, "max": 1440},
    {"name": "headway_minutes", "kind": "int", "min": 1, "max": 720},
    {"name": "service_window_start_min", "kind": "int", "min": 0, "max": 1439},
    {"name": "service_window_end_min", "kind": "int", "min": 0, "max": 1439},
    {"name": "demand_forecast_pax_per_hour", "kind": "int", "min": 0},
    {"name": "reference_seat_capacity", "kind": "int", "min": 1},
]

PUBLISH_SPEC = [{"name": "service_date", "kind": "date"}]

REPUBLISH_SPEC = [
    {"name": "service_date", "kind": "date"},
    {"name": "headway_minutes", "kind": "int", "min": 1, "max": 720},
    {"name": "expected_route_version", "kind": "int"},
]


@bp.post("/routes")
def create_route():
    authorize(["OpsPlanner"])
    data = validate_body(body(), CREATE_SPEC)
    if data["service_window_end_min"] < data["service_window_start_min"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'service_window_end_min' may not precede "
                       "'service_window_start_min'.")
    contract = must_exist(store.contracts, data["contract_id"], "ERR_CONTRACT_NOT_FOUND")
    row = store.base_row()
    row.update({
        "contract_id": contract["id"],
        "name": data["name"],
        "loop_minutes": data["loop_minutes"],
        "headway_minutes": data["headway_minutes"],
        "service_window_start_min": data["service_window_start_min"],
        "service_window_end_min": data["service_window_end_min"],
        "demand_forecast_pax_per_hour": data["demand_forecast_pax_per_hour"],
        "reference_seat_capacity": data["reference_seat_capacity"],
        "required_vehicle_count": 0,
        "ada_required_count": 0,
        "status": "DRAFT",
        "published_service_date": None,
    })
    calc.compute_route_fleet_requirement(row, contract)
    store.register_new(row)
    store.routes[row["id"]] = row
    return created(store.public(row))


@bp.get("/routes/<rid>")
def get_route(rid):
    authorize(ALL_ROLES)
    route = must_exist(store.routes, rid, "ERR_ROUTE_NOT_FOUND")
    return ok(store.public(route))


@bp.get("/routes")
def list_routes():
    authorize(ALL_ROLES)
    limit, offset = pagination()
    rows = list(store.routes.values())
    rows = equality_filter(rows, "contract_id", "contract_id")
    rows = equality_filter(rows, "status", "status")
    rows.sort(key=store.sort_key_created)
    return paginate(rows, limit, offset, store.public)


@bp.post("/routes/<rid>/publish")
def publish_route(rid):
    authorize(["OpsPlanner"])
    data = validate_body(body(), PUBLISH_SPEC)
    route = must_exist(store.routes, rid, "ERR_ROUTE_NOT_FOUND")
    if route["status"] != "DRAFT":
        raise ApiError("ERR_ROUTE_NOT_DRAFT")
    contract = store.contracts.get(route["contract_id"])
    if contract is None or contract["status"] not in calc.ACTIVE_CONTRACT_STATES:
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    service_date = data["service_date"]
    if not (contract["term_start_date"] <= service_date <= contract["term_end_date"]):
        raise ApiError("ERR_DATE_OUT_OF_TERM")

    route["status"] = "PUBLISHED"
    route["published_service_date"] = service_date
    calc.compute_route_fleet_requirement(route, contract)
    calc.generate_trips(route, service_date)
    touch(route)
    return ok(store.public(route))


@bp.post("/routes/<rid>/republish")
def republish_route(rid):
    authorize(["OpsPlanner"])
    data = validate_body(body(), REPUBLISH_SPEC)
    route = must_exist(store.routes, rid, "ERR_ROUTE_NOT_FOUND")
    if data["expected_route_version"] != route["version"]:
        raise ApiError("ERR_STALE_ROUTE_VERSION")
    if route["status"] not in ("PUBLISHED", "DEGRADED"):
        raise ApiError("ERR_ROUTE_NOT_PUBLISHED")
    contract = store.contracts.get(route["contract_id"])
    if contract is None or contract["status"] not in calc.ACTIVE_CONTRACT_STATES:
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    service_date = data["service_date"]
    if not (contract["term_start_date"] <= service_date <= contract["term_end_date"]):
        raise ApiError("ERR_DATE_OUT_OF_TERM")

    # cancel-and-regenerate cascade
    cancelled = []
    for trip in list(store.trips.values()):
        if trip["route_id"] != route["id"] or trip["service_date"] != service_date:
            continue
        if calc.cancel_trip(trip):
            cancelled.append(trip)
    for trip in cancelled:
        calc.revert_matched_requests_to_pending(trip)

    route["headway_minutes"] = data["headway_minutes"]
    calc.generate_trips(route, service_date)
    calc.compute_route_fleet_requirement(route, contract)
    route["published_service_date"] = service_date
    route["status"] = "PUBLISHED"
    touch(route)
    return ok(store.public(route))
