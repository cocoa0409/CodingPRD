"""VehicleLoad and LoadItem endpoints: staging, seal, dispatch cascade."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import errors
import serializers
from db import stamp_new, stamp_new_light, store, touch
from envelope import ok
from listing import page_out
from validators import as_dt, as_str, body, endpoint, get_or_404, req

bp = Blueprint("loads", __name__)

ALL_ROLES = ["CarrierAdmin", "ShipperComplianceOfficer", "Regulator"]

NON_TERMINAL_LOAD_STATES = ("STAGING", "SEALED", "DISPATCHED")


def _load_or_404(load_id):
    return get_or_404(store.loads, load_id, errors.ERR_LOAD_NOT_FOUND,
                      "VehicleLoad")


def _vehicle_of(load):
    return store.vehicles[load["vehicle_id"]]


def _carrier_of_vehicle(vehicle):
    return store.carriers[vehicle["carrier_id"]]


def _refresh_vehicle_status(vehicle):
    """Vehicle AVAILABLE when no non-terminal load remains, else LOADING —
    unless another load of this vehicle is DISPATCHED."""
    loads = [l for l in store.loads.values() if l["vehicle_id"] == vehicle["id"]]
    if any(l["status"] == "DISPATCHED" for l in loads):
        new = "DISPATCHED"
    elif any(l["status"] in ("STAGING", "SEALED") for l in loads):
        new = "LOADING"
    else:
        new = "AVAILABLE"
    if vehicle["status"] != new:
        vehicle["status"] = new
        touch(vehicle)


def _item_pairs(load_id):
    pairs = []
    for item in calc.load_items_of(load_id):
        shipment = store.shipments.get(item["shipment_id"])
        if shipment is None:
            continue
        pairs.append((shipment, store.materials[shipment["material_id"]]))
    return pairs


@bp.route("/hazmat/vehicles/<vehicleId>/loads", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def create_load(uid, role, vehicleId):
    vehicle = get_or_404(store.vehicles, vehicleId, errors.ERR_VEHICLE_NOT_FOUND,
                         "Vehicle")
    b = body()
    route_id = as_str(req(b, "route_id"), "route_id")
    dep = as_dt(req(b, "planned_departure_at"), "planned_departure_at")
    arr = as_dt(req(b, "planned_arrival_at"), "planned_arrival_at")
    if arr <= dep:
        raise errors.invalid(
            "planned_arrival_at must be strictly later than planned_departure_at")
    route = store.routes.get(route_id)
    if route is None:
        raise errors.ApiError(errors.ERR_INVALID_REFERENCE, 422,
                              "route_id does not reference an existing route")
    carrier = _carrier_of_vehicle(vehicle)
    if carrier["registration_status"] != "APPROVED_ACTIVE":
        raise errors.conflict(errors.ERR_CARRIER_NOT_ACTIVE,
                              "Carrier must be APPROVED_ACTIVE to create loads")
    # Half-open window overlap: touching endpoints do not conflict.
    for other in store.loads.values():
        if other["vehicle_id"] != vehicle["id"]:
            continue
        if other["status"] not in NON_TERMINAL_LOAD_STATES:
            continue
        if dep < other["planned_arrival_at"] and other["planned_departure_at"] < arr:
            raise errors.conflict(errors.ERR_LOAD_WINDOW_CONFLICT,
                                  "Load window overlaps another non-terminal load")
    load = {
        "vehicle_id": vehicle["id"],
        "route_id": route_id,
        "planned_departure_at": dep,
        "planned_arrival_at": arr,
        "total_table2_weight_kg": Decimal("0"),
        "required_placards": [],
        "handling_fee_cents": 0,
        "status": "STAGING",
    }
    stamp_new(load)
    store.loads[load["id"]] = load
    if vehicle["status"] == "AVAILABLE":
        vehicle["status"] = "LOADING"
        touch(vehicle)
    return ok(serializers.vehicle_load(load), 201)


@bp.route("/hazmat/vehicle-loads", methods=["GET"])
@endpoint(ALL_ROLES)
def list_loads(uid, role):
    rows = list(store.loads.values())
    vehicle_id = request.args.get("vehicle_id")
    if vehicle_id is not None:
        rows = [l for l in rows if l["vehicle_id"] == vehicle_id]
    route_id = request.args.get("route_id")
    if route_id is not None:
        rows = [l for l in rows if l["route_id"] == route_id]
    status = request.args.get("status")
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    return page_out(rows, serializers.vehicle_load)


@bp.route("/hazmat/vehicle-loads/<loadId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_load(uid, role, loadId):
    return ok(serializers.vehicle_load(_load_or_404(loadId)), 200)


@bp.route("/hazmat/vehicle-loads/<loadId>/items", methods=["GET"])
@endpoint(ALL_ROLES)
def list_load_items(uid, role, loadId):
    load = _load_or_404(loadId)
    return page_out(calc.load_items_of(load["id"]), serializers.load_item)


@bp.route("/hazmat/vehicle-loads/<loadId>/items", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def add_load_item(uid, role, loadId):
    load = _load_or_404(loadId)
    b = body()
    shipment_id = as_str(req(b, "shipment_id"), "shipment_id")
    position_code = as_str(req(b, "position_code"), "position_code")
    shipment = store.shipments.get(shipment_id)
    if shipment is None:
        raise errors.ApiError(errors.ERR_INVALID_REFERENCE, 422,
                              "shipment_id does not reference an existing shipment")
    if load["status"] != "STAGING":
        raise errors.conflict(errors.ERR_LOAD_NOT_STAGING,
                              "Item add requires STAGING")
    if shipment["status"] != "DOCUMENTED":
        raise errors.conflict(errors.ERR_SHIPMENT_NOT_DOCUMENTED,
                              "Item add requires shipment DOCUMENTED")
    material = store.materials[shipment["material_id"]]
    candidate = (shipment, material)
    if calc.candidate_violation(_item_pairs(load["id"]), candidate):
        raise errors.conflict(errors.ERR_SEGREGATION_VIOLATION,
                              "Forbidden hazard-class or segregation-group pair")
    for item in store.load_items.values():
        if item["shipment_id"] != shipment["id"]:
            continue
        other_load = store.loads.get(item["load_id"])
        if other_load is not None and other_load["status"] in NON_TERMINAL_LOAD_STATES:
            raise errors.conflict(errors.ERR_SHIPMENT_ALREADY_LOADED,
                                  "Shipment already on a non-terminal load")
    item = {
        "load_id": load["id"],
        "shipment_id": shipment["id"],
        "position_code": position_code,
    }
    stamp_new_light(item)
    store.load_items[item["id"]] = item
    load["total_table2_weight_kg"] = calc.total_table2_weight(load["id"])
    touch(load)
    return ok(serializers.load_item(item), 201)


@bp.route("/hazmat/vehicle-loads/<loadId>/items/<shipmentId>", methods=["DELETE"])
@endpoint(["ShipperComplianceOfficer"])
def remove_load_item(uid, role, loadId, shipmentId):
    load = _load_or_404(loadId)
    shipment = get_or_404(store.shipments, shipmentId, errors.ERR_SHIPMENT_NOT_FOUND,
                          "Shipment")
    if load["status"] != "STAGING":
        raise errors.conflict(errors.ERR_LOAD_NOT_STAGING,
                              "Item remove requires STAGING")
    item = None
    for i in store.load_items.values():
        if i["load_id"] == load["id"] and i["shipment_id"] == shipment["id"]:
            item = i
            break
    if item is None or shipment["status"] != "DOCUMENTED":
        raise errors.conflict(errors.ERR_SHIPMENT_NOT_REMOVABLE,
                              "Item removal requires shipment DOCUMENTED")
    del store.load_items[item["id"]]
    load["total_table2_weight_kg"] = calc.total_table2_weight(load["id"])
    touch(load)
    return ok(serializers.load_item(item), 200)


@bp.route("/hazmat/vehicle-loads/<loadId>/seal", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def seal_load(uid, role, loadId):
    load = _load_or_404(loadId)
    if load["status"] != "STAGING":
        raise errors.conflict(errors.ERR_LOAD_NOT_STAGING, "Seal requires STAGING")
    if not calc.load_items_of(load["id"]):
        raise errors.conflict(errors.ERR_LOAD_EMPTY,
                              "Seal requires at least one LoadItem")
    carrier = _carrier_of_vehicle(_vehicle_of(load))
    if carrier["registration_status"] != "APPROVED_ACTIVE":
        raise errors.conflict(errors.ERR_CARRIER_NOT_ACTIVE,
                              "Seal requires carrier APPROVED_ACTIVE")
    if calc.segregation_violation(_item_pairs(load["id"])):
        raise errors.conflict(errors.ERR_SEGREGATION_VIOLATION,
                              "Forbidden hazard-class or segregation-group pair")
    placards, weight = calc.placard_determination(load["id"], carrier)
    load["total_table2_weight_kg"] = weight
    load["required_placards"] = placards
    load["handling_fee_cents"] = calc.load_handling_fee(load["id"], placards)
    load["status"] = "SEALED"
    touch(load)
    return ok(serializers.vehicle_load(load), 200)


@bp.route("/hazmat/vehicle-loads/<loadId>/unseal", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def unseal_load(uid, role, loadId):
    load = _load_or_404(loadId)
    if load["status"] != "SEALED":
        raise errors.conflict(errors.ERR_LOAD_NOT_SEALED, "Unseal requires SEALED")
    load["status"] = "STAGING"
    load["required_placards"] = []
    load["handling_fee_cents"] = 0
    touch(load)
    return ok(serializers.vehicle_load(load), 200)


@bp.route("/hazmat/vehicle-loads/<loadId>/dispatch", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def dispatch_load(uid, role, loadId):
    load = _load_or_404(loadId)
    if load["status"] != "SEALED":
        raise errors.conflict(errors.ERR_LOAD_NOT_SEALED, "Dispatch requires SEALED")
    pairs = _item_pairs(load["id"])
    for shipment, _m in pairs:
        if shipment["status"] != "TENDERED":
            raise errors.conflict(errors.ERR_SHIPMENT_NOT_TENDERED,
                                  "Dispatch requires every item shipment TENDERED")
    route = store.routes[load["route_id"]]
    clock = store.clock
    if not (route["effective_from"] <= clock <= route["effective_to"]):
        raise errors.conflict(errors.ERR_ROUTE_NOT_EFFECTIVE,
                              "Route effective window does not cover the clock")
    if route["is_restricted_corridor"]:
        for _s, material in pairs:
            if material["hazard_class"] not in route["allowed_hazard_classes"]:
                raise errors.conflict(errors.ERR_ROUTE_RESTRICTED_CLASS,
                                      "Restricted corridor does not allow an item class")
    for shipment, _m in pairs:
        plan_id = shipment["pinned_security_plan_id"]
        if plan_id is None:
            continue
        plan = store.security_plans.get(plan_id)
        if (plan is None or plan["status"] != "APPROVED"
                or plan["version"] != shipment["pinned_security_plan_version"]):
            raise errors.conflict(errors.ERR_STALE_SECURITY_PLAN,
                                  "Pinned security plan is no longer current")
    carrier = _carrier_of_vehicle(_vehicle_of(load))
    if carrier["registration_status"] != "APPROVED_ACTIVE":
        raise errors.conflict(errors.ERR_CARRIER_NOT_ACTIVE,
                              "Dispatch requires carrier APPROVED_ACTIVE")
    vehicle = _vehicle_of(load)
    if vehicle["status"] != "LOADING":
        raise errors.conflict(errors.ERR_VEHICLE_NOT_DISPATCHABLE,
                              "Dispatch requires vehicle LOADING")
    load["status"] = "DISPATCHED"
    touch(load)
    vehicle["status"] = "DISPATCHED"
    touch(vehicle)
    for shipment, _m in pairs:
        shipment["status"] = "IN_TRANSIT"
        touch(shipment)
        for paper in store.papers.values():
            if paper["shipment_id"] == shipment["id"] and paper["status"] == "CERTIFIED":
                paper["status"] = "LOCKED_IN_TRANSIT"
                touch(paper)
    return ok(serializers.vehicle_load(load), 200)


@bp.route("/hazmat/vehicle-loads/<loadId>/arrive", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def arrive_load(uid, role, loadId):
    load = _load_or_404(loadId)
    if load["status"] != "DISPATCHED":
        raise errors.conflict(errors.ERR_LOAD_NOT_DISPATCHED,
                              "Arrive requires DISPATCHED")
    load["status"] = "ARRIVED"
    touch(load)
    for shipment, _m in _item_pairs(load["id"]):
        if shipment["status"] == "IN_TRANSIT":
            shipment["status"] = "DELIVERED"
            touch(shipment)
    _refresh_vehicle_status(_vehicle_of(load))
    return ok(serializers.vehicle_load(load), 200)


@bp.route("/hazmat/vehicle-loads/<loadId>/void", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def void_load(uid, role, loadId):
    load = _load_or_404(loadId)
    if load["status"] not in ("STAGING", "SEALED"):
        raise errors.conflict(errors.ERR_LOAD_NOT_VOIDABLE,
                              "Void requires STAGING or SEALED")
    for item in calc.load_items_of(load["id"]):
        shipment = store.shipments.get(item["shipment_id"])
        if shipment is not None and shipment["status"] == "TENDERED":
            shipment["status"] = "DOCUMENTED"  # pin fields kept
            touch(shipment)
        del store.load_items[item["id"]]
    load["status"] = "VOIDED"
    load["required_placards"] = []
    load["handling_fee_cents"] = 0
    load["total_table2_weight_kg"] = Decimal("0")
    touch(load)
    _refresh_vehicle_status(_vehicle_of(load))
    return ok(serializers.vehicle_load(load), 200)
