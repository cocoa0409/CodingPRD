"""Vehicle, Driver and MaintenanceOrder endpoints (PRD 3.3 / 3.4)."""

from decimal import Decimal

from flask import Blueprint

import calc
import store
from envelope import created, ok, paginate, pagination
from errors import ApiError
from guards import (ALL_ROLES, authorize, body, bool_param, equality_filter,
                    id_field, must_exist, validate_body)
from store import touch

bp = Blueprint("fleet", __name__)

VEHICLE_SPEC = [
    {"name": "fleet_code", "kind": "string", "min_len": 1, "max_len": 40},
    {"name": "seat_capacity", "kind": "int", "min": 1},
    {"name": "is_ada_accessible", "kind": "bool"},
    {"name": "odometer_km", "kind": "int", "min": 0},
    {"name": "service_interval_km", "kind": "int", "min": 1},
    id_field("branding_contract_id", required=False, nullable=True),
]

BRAND_SPEC = [id_field("branding_contract_id", nullable=True)]

DRIVER_SPEC = [
    {"name": "full_name", "kind": "string", "min_len": 1, "max_len": 120},
    {"name": "license_class", "kind": "enum", "values": ("CDL_B", "CDL_C")},
    {"name": "ada_certified", "kind": "bool"},
    {"name": "max_duty_minutes_per_day", "kind": "int", "min": 1, "max": 1440},
]

ORDER_SPEC = [
    id_field("vehicle_id"),
    {"name": "kind", "kind": "enum", "values": ("PREVENTIVE", "CORRECTIVE", "BRANDING_WRAP")},
    {"name": "service_date", "kind": "date"},
    {"name": "window_start_min", "kind": "int", "min": 0, "max": 1439},
    {"name": "window_end_min", "kind": "int", "min": 0, "max": 1439},
]

CLOSE_SPEC = [{"name": "outcome", "kind": "enum", "values": ("RETURN_TO_SERVICE", "RETIRE")}]


def _check_ada_fleet_floor(contract, branded_total, branded_ada):
    """PRD 3.3: the branded ADA share is evaluated AFTER the wrap takes effect."""
    if branded_total <= 0:
        return
    share = calc.rhu(Decimal(100) * Decimal(branded_ada) / Decimal(branded_total), 2)
    if share < calc.dec(contract["ada_min_accessible_pct"]):
        raise ApiError("ERR_ADA_FLEET_SHORTFALL")


# --------------------------------------------------------------------- vehicles
@bp.post("/vehicles")
def create_vehicle():
    authorize(["FleetManager"])
    data = validate_body(body(), VEHICLE_SPEC)
    contract = None
    if data.get("branding_contract_id") is not None:
        contract = must_exist(store.contracts, data["branding_contract_id"],
                              "ERR_CONTRACT_NOT_FOUND")
        existing = [v for v in store.vehicles.values()
                    if v["branding_contract_id"] == contract["id"]
                    and v["status"] in ("AVAILABLE", "IN_MAINTENANCE")]
        branded_total = len(existing) + 1
        branded_ada = sum(1 for v in existing if v["is_ada_accessible"]) + (
            1 if data["is_ada_accessible"] else 0)
        _check_ada_fleet_floor(contract, branded_total, branded_ada)
    for existing in store.vehicles.values():
        if existing["fleet_code"] == data["fleet_code"]:
            raise ApiError("ERR_FLEET_CODE_DUPLICATE")

    row = store.base_row()
    row.update({
        "fleet_code": data["fleet_code"],
        "seat_capacity": data["seat_capacity"],
        "is_ada_accessible": data["is_ada_accessible"],
        "odometer_km": data["odometer_km"],
        "service_interval_km": data["service_interval_km"],
        "branding_contract_id": data.get("branding_contract_id"),
        "status": "AVAILABLE",
        "committed_block_minutes": 0,
    })
    store.register_new(row)
    store.vehicles[row["id"]] = row
    if contract is not None:
        calc.recompute_contract_branded_counts(contract)
    return created(store.public(row))


@bp.get("/vehicles/<vid>")
def get_vehicle(vid):
    authorize(ALL_ROLES)
    return ok(store.public(must_exist(store.vehicles, vid, "ERR_VEHICLE_NOT_FOUND")))


@bp.get("/vehicles")
def list_vehicles():
    authorize(ALL_ROLES)
    limit, offset = pagination()
    rows = list(store.vehicles.values())
    rows = equality_filter(rows, "branding_contract_id", "branding_contract_id")
    rows = equality_filter(rows, "status", "status")
    rows = equality_filter(rows, "is_ada_accessible", "is_ada_accessible", coerce=bool_param)
    rows.sort(key=store.sort_key_created)
    return paginate(rows, limit, offset, store.public)


@bp.post("/vehicles/<vid>/brand")
def brand_vehicle(vid):
    authorize(["FleetManager"])
    data = validate_body(body(), BRAND_SPEC)
    vehicle = must_exist(store.vehicles, vid, "ERR_VEHICLE_NOT_FOUND")
    target = None
    if data["branding_contract_id"] is not None:
        target = must_exist(store.contracts, data["branding_contract_id"],
                            "ERR_CONTRACT_NOT_FOUND")
        branded_total, branded_ada = calc.branded_counts_after_wrap(target, vehicle)
        _check_ada_fleet_floor(target, branded_total, branded_ada)

    previous_id = vehicle["branding_contract_id"]
    vehicle["branding_contract_id"] = data["branding_contract_id"]
    touch(vehicle)
    if target is not None:
        calc.recompute_contract_branded_counts(target)
    if previous_id and (target is None or previous_id != target["id"]):
        previous = store.contracts.get(previous_id)
        if previous is not None:
            calc.recompute_contract_branded_counts(previous)
    return ok(store.public(vehicle))


@bp.get("/vehicles/<vid>/maintenance-orders")
def list_vehicle_orders(vid):
    authorize(ALL_ROLES)
    limit, offset = pagination()
    vehicle = must_exist(store.vehicles, vid, "ERR_VEHICLE_NOT_FOUND")
    rows = [o for o in store.maintenance_orders.values() if o["vehicle_id"] == vehicle["id"]]
    rows = equality_filter(rows, "status", "status")
    rows.sort(key=store.sort_key_created, reverse=True)
    return paginate(rows, limit, offset, store.public)


# ---------------------------------------------------------------------- drivers
@bp.post("/drivers")
def create_driver():
    authorize(["OpsPlanner"])
    data = validate_body(body(), DRIVER_SPEC)
    row = store.base_row()
    row.update({
        "full_name": data["full_name"],
        "license_class": data["license_class"],
        "ada_certified": data["ada_certified"],
        "max_duty_minutes_per_day": data["max_duty_minutes_per_day"],
        "assigned_duty_minutes_current_date": 0,
    })
    store.register_new(row)
    store.drivers[row["id"]] = row
    return created(store.public(row))


@bp.get("/drivers/<did>")
def get_driver(did):
    authorize(ALL_ROLES)
    return ok(store.public(must_exist(store.drivers, did, "ERR_DRIVER_NOT_FOUND")))


# ------------------------------------------------------------ maintenance orders
@bp.post("/maintenance-orders")
def create_maintenance_order():
    authorize(["FleetManager"])
    data = validate_body(body(), ORDER_SPEC)
    if data["window_end_min"] < data["window_start_min"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'window_end_min' may not precede 'window_start_min'.")
    vehicle = must_exist(store.vehicles, data["vehicle_id"], "ERR_VEHICLE_NOT_FOUND")

    order = store.base_row()
    order.update({
        "vehicle_id": vehicle["id"],
        "kind": data["kind"],
        "service_date": data["service_date"],
        "window_start_min": data["window_start_min"],
        "window_end_min": data["window_end_min"],
        "odometer_at_open": vehicle["odometer_km"],
        "status": "OPEN",
        "outcome": None,
        "displaced_trip_count": 0,
    })
    store.register_new(order)
    store.maintenance_orders[order["id"]] = order

    same_day = order["service_date"] == store.clock_service_date()
    if same_day and vehicle["status"] == "AVAILABLE":
        vehicle["status"] = "IN_MAINTENANCE"
        displaced = []
        for trip in list(store.trips.values()):
            if trip["vehicle_id"] != vehicle["id"]:
                continue
            if trip["service_date"] != order["service_date"]:
                continue
            if trip["dispatch_status"] != "ASSIGNED":
                continue
            if trip["scheduled_departure_min"] > order["window_end_min"]:
                continue
            if order["window_start_min"] > trip["scheduled_arrival_min"]:
                continue
            trip["dispatch_status"] = "SCHEDULED"
            calc.release_trip_bindings(trip)
            touch(trip)
            displaced.append(trip)
        order["displaced_trip_count"] = len(displaced)
        for trip in displaced:
            calc.revert_matched_requests_to_pending(trip)
        calc.recompute_vehicle_committed_block_minutes(vehicle)
        touch(vehicle)
        seen = set()
        for trip in displaced:
            if trip["route_id"] in seen:
                continue
            seen.add(trip["route_id"])
            route = store.routes.get(trip["route_id"])
            if route is not None:
                calc.check_route_degradation(route, order["service_date"])
    return created(store.public(order))


@bp.post("/maintenance-orders/<oid>/close")
def close_maintenance_order(oid):
    authorize(["FleetManager"])
    data = validate_body(body(), CLOSE_SPEC)
    order = must_exist(store.maintenance_orders, oid, "ERR_MAINTENANCE_ORDER_NOT_FOUND")
    if order["status"] != "OPEN":
        raise ApiError("ERR_MAINTENANCE_ORDER_NOT_OPEN")

    order["status"] = "CLOSED"
    order["outcome"] = data["outcome"]
    touch(order)

    vehicle = store.vehicles.get(order["vehicle_id"])
    if vehicle is not None and vehicle["status"] == "IN_MAINTENANCE":
        if data["outcome"] == "RETURN_TO_SERVICE":
            vehicle["status"] = "AVAILABLE"
            touch(vehicle)
        else:
            vehicle["status"] = "RETIRED"
            previous_id = vehicle["branding_contract_id"]
            vehicle["branding_contract_id"] = None
            touch(vehicle)
            if previous_id:
                previous = store.contracts.get(previous_id)
                if previous is not None:
                    calc.recompute_contract_branded_counts(previous)
    return ok(store.public(order))
