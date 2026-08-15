"""Shipment and ShipmentLine endpoints (PRD §3.5)."""

from flask import Blueprint, request
import errors
from db import store
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import domain
from util import (body, req_str, opt_str, opt_int, new_resource, touch,
                  pagination_params, paginate, sort_by_created)

bp = Blueprint("shipments", __name__)

READ_ROLES = {"OpsManager", "TourManager", "LogisticsCoordinator", "WarehouseTech"}

# Case size adequacy ladder: a case must be >= the gear's weight-class
# requirement mapping (SCAFFOLD FlightCase.size_class)
SIZE_ORDER = {"SMALL": 0, "MEDIUM": 1, "LARGE": 2, "TRUNK": 3}
# Minimum case size per unit weight class
WEIGHT_CLASS_MIN_SIZE = {
    "HAND_CARRY": "SMALL",
    "STANDARD": "MEDIUM",
    "HEAVY": "LARGE",
    "OVERSIZE": "TRUNK",
}


def _check_capacity_and_case(shipment, gear_unit_id, flight_case_id, weight_kg):
    """Gate 11 (capacity) before gate 12 (flight case) per PRD §2.11."""
    unit = domain.get_gear_unit(gear_unit_id)
    # Gate 11: booked weight may reach but never exceed capacity
    prospective = shipment.get("booked_weight_kg", 0) + weight_kg
    if prospective > shipment.get("capacity_kg", 0):
        raise errors.capacity_exceeded("Shipment capacity exceeded")
    # Gate 12: unit requiring a case must name an AVAILABLE, adequately sized one
    if unit.get("flight_case_required"):
        if not flight_case_id:
            raise errors.flight_case_required("Unit requires a flight case")
        case = store.flight_cases.get(flight_case_id)
        if case is None:
            raise errors.not_found("FlightCase not found")
        if case.get("status") != "AVAILABLE":
            raise errors.flight_case_required("Flight case is not AVAILABLE")
        model = store.gear_models.get(unit.get("gear_model_id"))
        min_size = WEIGHT_CLASS_MIN_SIZE.get(model.get("weight_class"), "SMALL")
        if SIZE_ORDER.get(case.get("size_class"), 0) < SIZE_ORDER.get(min_size, 0):
            raise errors.flight_case_required("Flight case size_class inadequate")
    return unit


@bp.route("/backline/shipments", methods=["POST"])
def create_shipment():
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    data = body()
    tour_id = req_str(data, "tour_id")
    domain.get_tour(tour_id)
    capacity = opt_int(data, "capacity_kg")
    if capacity is None:
        raise errors.invalid_request("Missing required field: capacity_kg")
    if capacity <= 0:
        raise errors.invalid_request("capacity_kg must be > 0")
    if data.get("ship_date") is None:
        raise errors.invalid_request("Missing required field: ship_date")
    shipment = new_resource()
    shipment.update({
        "tour_id": tour_id,
        "from_city_code": req_str(data, "from_city_code"),
        "to_city_code": req_str(data, "to_city_code"),
        "ship_date": data.get("ship_date"),
        "status": "PLANNED",
        "tech_labor_minutes": 0,
        "capacity_kg": capacity,
        "booked_weight_kg": 0,
    })
    store.shipments[shipment["id"]] = shipment
    return success_object(domain.serialize(shipment), status=201)


@bp.route("/backline/shipments/<shipment_id>", methods=["GET"])
def fetch_shipment(shipment_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    shipment = domain.get_shipment(shipment_id)
    return success_object(domain.serialize(shipment), status=200)


@bp.route("/backline/shipments", methods=["GET"])
def list_shipments():
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    limit, offset = pagination_params()
    tour_id = request.args.get("tour_id")
    status = request.args.get("status")
    items = list(store.shipments.values())
    if tour_id is not None:
        items = [s for s in items if s.get("tour_id") == tour_id]
    if status is not None:
        items = [s for s in items if s.get("status") == status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(s) for s in page], meta, status=200)


@bp.route("/backline/shipments/<shipment_id>/lines", methods=["POST"])
def book_shipment_line(shipment_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    shipment = domain.get_shipment(shipment_id)
    data = body()
    gear_unit_id = req_str(data, "gear_unit_id")
    flight_case_id = opt_str(data, "flight_case_id", default=None)
    weight_kg = opt_int(data, "weight_kg", minimum=0)
    if weight_kg is None:
        raise errors.invalid_request("Missing required field: weight_kg")
    labor_minutes = opt_int(data, "labor_minutes", minimum=0)
    if labor_minutes is None:
        raise errors.invalid_request("Missing required field: labor_minutes")
    # Constraints enforced at booking (capacity before case, §2.11)
    _check_capacity_and_case(shipment, gear_unit_id, flight_case_id, weight_kg)
    line = new_resource()
    line.update({
        "shipment_id": shipment["id"],
        "gear_unit_id": gear_unit_id,
        "flight_case_id": flight_case_id,
        "weight_kg": weight_kg,
        "labor_minutes": labor_minutes,
        "status": "BOOKED",
    })
    store.shipment_lines[line["id"]] = line
    domain.reconcile_shipment_aggregates(shipment)
    return success_object(domain.serialize(line), status=201)


@bp.route("/backline/shipments/<shipment_id>/lines", methods=["GET"])
def list_shipment_lines(shipment_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    domain.get_shipment(shipment_id)
    limit, offset = pagination_params()
    items = [sl for sl in store.shipment_lines.values() if sl.get("shipment_id") == shipment_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(sl) for sl in page], meta, status=200)


@bp.route("/backline/shipments/<shipment_id>/begin-loading", methods=["POST"])
def begin_loading(shipment_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    shipment = domain.get_shipment(shipment_id)
    if shipment["status"] != "PLANNED":
        raise errors.invalid_state("Shipment must be PLANNED to begin loading")
    shipment["status"] = "LOADING"
    touch(shipment)
    return success_object(domain.serialize(shipment), status=200)


@bp.route("/backline/shipment-lines/<line_id>/load", methods=["POST"])
def load_shipment_line(line_id):
    auth = get_auth()
    require_roles(auth, {"WarehouseTech"})
    line = domain.get_shipment_line(line_id)
    if line["status"] != "BOOKED":
        raise errors.invalid_state("Shipment line must be BOOKED to load")
    shipment = domain.get_shipment(line["shipment_id"])
    if shipment["status"] != "LOADING":
        raise errors.invalid_state("Parent shipment must be LOADING to load a line")
    # Re-check capacity (gate 11) and case adequacy (gate 12) at loading (§3.5).
    # The line's own weight already counts toward booked_weight_kg since booking.
    if shipment.get("booked_weight_kg", 0) > shipment.get("capacity_kg", 0):
        raise errors.capacity_exceeded("Shipment capacity exceeded")
    unit = domain.get_gear_unit(line["gear_unit_id"])
    if unit.get("flight_case_required"):
        if not line.get("flight_case_id"):
            raise errors.flight_case_required("Unit requires a flight case")
        case = store.flight_cases.get(line["flight_case_id"])
        if case is None:
            raise errors.not_found("FlightCase not found")
        if case.get("status") != "AVAILABLE":
            raise errors.flight_case_required("Flight case is not AVAILABLE")
        model = store.gear_models.get(unit.get("gear_model_id"))
        min_size = WEIGHT_CLASS_MIN_SIZE.get(model.get("weight_class"), "SMALL")
        if SIZE_ORDER.get(case.get("size_class"), 0) < SIZE_ORDER.get(min_size, 0):
            raise errors.flight_case_required("Flight case size_class inadequate")
        # Assigned case flips AVAILABLE -> ASSIGNED
        case["status"] = "ASSIGNED"
        touch(case)
    line["status"] = "LOADED"
    touch(line)
    domain.reconcile_shipment_aggregates(shipment)
    return success_object(domain.serialize(line), status=200)


@bp.route("/backline/shipment-lines/<line_id>/cancel", methods=["POST"])
def cancel_shipment_line(line_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    line = domain.get_shipment_line(line_id)
    if line["status"] != "BOOKED":
        raise errors.invalid_state("Only a BOOKED shipment line may be cancelled")
    shipment = domain.get_shipment(line["shipment_id"])
    line["status"] = "CANCELLED"
    touch(line)
    domain.reconcile_shipment_aggregates(shipment)
    return success_object(domain.serialize(line), status=200)


@bp.route("/backline/shipments/<shipment_id>/depart", methods=["POST"])
def depart(shipment_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    shipment = domain.get_shipment(shipment_id)
    if shipment["status"] != "LOADING":
        raise errors.invalid_state("Shipment must be LOADING to depart")
    # Every line must be LOADED or CANCELLED
    for line in store.shipment_lines.values():
        if line.get("shipment_id") == shipment["id"] and \
                line.get("status") not in {"LOADED", "CANCELLED"}:
            raise errors.invalid_state("All lines must be LOADED or CANCELLED to depart")
    # Re-validate booked weight within capacity
    if shipment.get("booked_weight_kg", 0) > shipment.get("capacity_kg", 0):
        raise errors.capacity_exceeded("Shipment capacity exceeded")
    # Loaded lines' units OUT_ON_RENTAL -> IN_TRANSIT; cases ASSIGNED -> IN_TRANSIT
    for line in store.shipment_lines.values():
        if line.get("shipment_id") == shipment["id"] and line.get("status") == "LOADED":
            unit = store.gear_units.get(line.get("gear_unit_id"))
            if unit is not None and unit.get("status") == "OUT_ON_RENTAL":
                unit["status"] = "IN_TRANSIT"
                touch(unit)
            case = store.flight_cases.get(line.get("flight_case_id")) if line.get("flight_case_id") else None
            if case is not None and case.get("status") == "ASSIGNED":
                case["status"] = "IN_TRANSIT"
                touch(case)
    shipment["status"] = "IN_TRANSIT"
    touch(shipment)
    return success_object(domain.serialize(shipment), status=200)


@bp.route("/backline/shipments/<shipment_id>/mark-delivered", methods=["POST"])
def mark_shipment_delivered(shipment_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    shipment = domain.get_shipment(shipment_id)
    if shipment["status"] != "IN_TRANSIT":
        raise errors.invalid_state("Shipment must be IN_TRANSIT to mark delivered")
    # Non-cancelled lines -> DELIVERED; units IN_TRANSIT -> OUT_ON_RENTAL;
    # cases IN_TRANSIT -> AVAILABLE with home_city_code rewritten to destination
    for line in store.shipment_lines.values():
        if line.get("shipment_id") == shipment["id"] and line.get("status") != "CANCELLED":
            if line.get("status") == "LOADED":
                line["status"] = "DELIVERED"
                touch(line)
            unit = store.gear_units.get(line.get("gear_unit_id"))
            if unit is not None and unit.get("status") == "IN_TRANSIT":
                unit["status"] = "OUT_ON_RENTAL"
                touch(unit)
            case = store.flight_cases.get(line.get("flight_case_id")) if line.get("flight_case_id") else None
            if case is not None and case.get("status") == "IN_TRANSIT":
                case["status"] = "AVAILABLE"
                case["home_city_code"] = shipment["to_city_code"]
                touch(case)
    shipment["status"] = "DELIVERED"
    touch(shipment)
    return success_object(domain.serialize(shipment), status=200)


@bp.route("/backline/shipments/<shipment_id>/close", methods=["POST"])
def close_shipment(shipment_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    shipment = domain.get_shipment(shipment_id)
    if shipment["status"] != "DELIVERED":
        raise errors.invalid_state("Shipment must be DELIVERED to close")
    shipment["status"] = "CLOSED"
    touch(shipment)
    return success_object(domain.serialize(shipment), status=200)


@bp.route("/backline/shipments/<shipment_id>/cancel", methods=["POST"])
def cancel_shipment(shipment_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    shipment = domain.get_shipment(shipment_id)
    if shipment["status"] not in {"PLANNED", "LOADING"}:
        raise errors.invalid_state("Only PLANNED or LOADING shipments may be cancelled")
    # No line may have reached LOADED
    for line in store.shipment_lines.values():
        if line.get("shipment_id") == shipment["id"] and line.get("status") == "LOADED":
            raise errors.invalid_state("Cannot cancel a shipment with LOADED lines")
    # Each BOOKED line -> CANCELLED; each assigned case released to AVAILABLE
    for line in store.shipment_lines.values():
        if line.get("shipment_id") == shipment["id"] and line.get("status") == "BOOKED":
            line["status"] = "CANCELLED"
            touch(line)
            case = store.flight_cases.get(line.get("flight_case_id")) if line.get("flight_case_id") else None
            if case is not None and case.get("status") == "ASSIGNED":
                case["status"] = "AVAILABLE"
                touch(case)
    domain.reconcile_shipment_aggregates(shipment)
    shipment["status"] = "CANCELLED"
    touch(shipment)
    return success_object(domain.serialize(shipment), status=200)
