"""Delivery routes: plan/dispatch/depart/complete/raise-exception/reroute."""

from flask import Blueprint, g, request

import clock
import db
import errors
import helpers
import response
import serializers
from middleware import auth_required
from services import audit


bp = Blueprint("delivery_routes", __name__, url_prefix="/supply-chain/delivery-routes")


VALID_ZONES = {"AMBIENT", "CHILLED", "FROZEN"}


def _normalize_stops(stops):
    """Validate and parse planned_stops payload. Returns list of stop dicts."""
    if not isinstance(stops, list) or not stops:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "planned_stops must be a non-empty array.")

    parsed = []
    for s in stops:
        if not isinstance(s, dict):
            errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "Each stop must be an object.")
        for k in ["store_id", "time_window_start", "time_window_end", "batch_ids"]:
            if k not in s:
                errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, f"Stop missing field: {k}")
        if not isinstance(s["batch_ids"], list) or not s["batch_ids"]:
            errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "batch_ids must be a non-empty array.")
        ws = clock.parse_iso(s["time_window_start"])
        we = clock.parse_iso(s["time_window_end"])
        if ws >= we:
            errors.raise_error(errors.ERR_DELIVERY_WINDOW_OVERLAP,
                               "time_window_start must be < time_window_end.")
        parsed.append({
            "store_id": s["store_id"],
            "time_window_start": ws,
            "time_window_end": we,
            "batch_ids": list(s["batch_ids"]),
        })
    return parsed


def _validate_no_overlap(stops):
    sorted_stops = sorted(stops, key=lambda s: s["time_window_start"])
    for i in range(len(sorted_stops) - 1):
        a = sorted_stops[i]
        b = sorted_stops[i + 1]
        # Half-open intervals [start, end). Overlap if a.end > b.start.
        if a["time_window_end"] > b["time_window_start"]:
            errors.raise_error(errors.ERR_DELIVERY_WINDOW_OVERLAP,
                               "Two stops have overlapping time windows.")


def _compute_loaded_and_zones(stops):
    total_units = 0
    required_zones = set()
    for s in stops:
        for bid in s["batch_ids"]:
            batch = db.production_batches.get(bid)
            if batch is None:
                errors.raise_error(errors.ERR_REFERENCE_NOT_FOUND, f"ProductionBatch {bid} not found.")
            total_units += batch["planned_units"]
            recipe = db.recipes[batch["recipe_id"]]
            required_zones.add(recipe["temperature_zone"])
    return total_units, required_zones


@bp.route("", methods=["POST"])
@auth_required("CentralKitchenPlanner")
def plan_route():
    body = helpers.get_json_body()
    for f in ["vehicle_id", "driver_user_id", "planned_stops", "target_delivery_date"]:
        if f not in body:
            errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, f"Missing field: {f}")

    vehicle = db.vehicles.get(body["vehicle_id"])
    if vehicle is None:
        errors.raise_error(errors.ERR_REFERENCE_NOT_FOUND, "Vehicle not found.")

    stops = _normalize_stops(body["planned_stops"])
    # Verify each store_id is real.
    for s in stops:
        if s["store_id"] not in db.stores:
            errors.raise_error(errors.ERR_REFERENCE_NOT_FOUND, f"Store {s['store_id']} not found.")
    _validate_no_overlap(stops)

    total_loaded, required_zones = _compute_loaded_and_zones(stops)

    # All batches must share the target_delivery_date.
    tdd = body["target_delivery_date"]
    for s in stops:
        for bid in s["batch_ids"]:
            batch = db.production_batches[bid]
            if batch["target_delivery_date"] != tdd:
                errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE,
                                   "All batches must share the route's target_delivery_date.")

    if total_loaded > vehicle["capacity_units"]:
        errors.raise_error(errors.ERR_VEHICLE_CAPACITY_EXCEEDED,
                           "Loaded units exceed vehicle capacity.")
    if not required_zones.issubset(set(vehicle["temperature_zones"])):
        errors.raise_error(errors.ERR_TEMPERATURE_ZONE_INCOMPATIBLE,
                           "Required zones not satisfied by vehicle.")

    rid = db.new_id()
    common = helpers.common_create()
    route = {
        "id": rid,
        "vehicle_id": vehicle["id"],
        "driver_user_id": body["driver_user_id"],
        "planned_stops": stops,
        "total_units_loaded": total_loaded,
        "required_zones": sorted(required_zones),
        "target_delivery_date": tdd,
        "dispatched_at": None,
        "completed_at": None,
        "exception_reason": None,
        "status": "PLANNED",
        **common,
    }
    db.delivery_routes[rid] = route
    audit.append(target_type="DeliveryRoute", target_id=rid, action="PLAN_ROUTE",
                 payload={"vehicle_id": vehicle["id"], "stop_count": len(stops)})
    return response.created(serializers.delivery_route_dict(route))


@bp.route("", methods=["GET"])
@auth_required("CentralKitchenPlanner", "Driver")
def list_routes():
    limit, offset = helpers.parse_pagination()
    items = list(db.delivery_routes.values())
    status_filter = request.args.get("status")
    driver_filter = request.args.get("driver_user_id")
    if g.user_role == "Driver":
        items = [r for r in items if r["driver_user_id"] == g.user_id]
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    if driver_filter:
        items = [r for r in items if r["driver_user_id"] == driver_filter]
    items.sort(key=lambda r: r["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([serializers.delivery_route_dict(r) for r in page],
                            limit=limit, offset=offset, total_count=total)


@bp.route("/<rid>/dispatch", methods=["POST"])
@auth_required("CentralKitchenPlanner")
def dispatch(rid):
    route = db.delivery_routes.get(rid)
    if route is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"DeliveryRoute {rid} not found.")
    if route["status"] != "PLANNED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only PLANNED routes may be dispatched.")
    body = helpers.get_json_body()
    helpers.check_occ(route, body.get("version"))

    vehicle = db.vehicles[route["vehicle_id"]]
    # Per validation priority: temperature zone (priority 9) before vehicle availability (priority 20)
    # and before constraints (capacity priority 19).
    required_zones = set(route["required_zones"])
    if not required_zones.issubset(set(vehicle["temperature_zones"])):
        errors.raise_error(errors.ERR_TEMPERATURE_ZONE_INCOMPATIBLE,
                           "Required zones not satisfied by vehicle at dispatch time.")
    # Ensure all batches are COMPLETED.
    for stop in route["planned_stops"]:
        for bid in stop["batch_ids"]:
            batch = db.production_batches.get(bid)
            if batch is None or batch["status"] != "COMPLETED":
                errors.raise_error(errors.ERR_BATCH_NOT_READY,
                                   "Loaded batch is not in COMPLETED state.")
    # Check stop time-window non-overlap.
    _validate_no_overlap(route["planned_stops"])
    if route["total_units_loaded"] > vehicle["capacity_units"]:
        errors.raise_error(errors.ERR_VEHICLE_CAPACITY_EXCEEDED, "Capacity exceeded at dispatch.")
    if vehicle["status"] != "AVAILABLE":
        errors.raise_error(errors.ERR_VEHICLE_NOT_AVAILABLE,
                           "Vehicle is not AVAILABLE.")

    vehicle["status"] = "ASSIGNED"
    helpers.bump(vehicle)
    route["status"] = "DISPATCHED"
    route["dispatched_at"] = clock.now()
    helpers.bump(route)
    audit.append(target_type="DeliveryRoute", target_id=rid, action="DISPATCH_ROUTE",
                 payload={"vehicle_id": vehicle["id"]},
                 external_systems=["LOGISTICS"])
    audit.append(target_type="Vehicle", target_id=vehicle["id"], action="VEHICLE_ASSIGNED",
                 payload={"route_id": rid})
    return response.ok(serializers.delivery_route_dict(route))


def _ensure_driver_match(route):
    if g.user_id != route["driver_user_id"]:
        errors.raise_error(errors.ERR_DRIVER_MISMATCH,
                           "Driver does not match the route's driver_user_id.")


@bp.route("/<rid>/depart", methods=["POST"])
@auth_required("Driver")
def depart(rid):
    route = db.delivery_routes.get(rid)
    if route is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"DeliveryRoute {rid} not found.")
    if route["status"] not in ("DISPATCHED", "REROUTED"):
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Only DISPATCHED or REROUTED routes may be departed.")
    _ensure_driver_match(route)

    route["status"] = "IN_TRANSIT"
    helpers.bump(route)
    audit.append(target_type="DeliveryRoute", target_id=rid, action="DEPART_ROUTE", payload={})
    return response.ok(serializers.delivery_route_dict(route))


@bp.route("/<rid>/complete", methods=["POST"])
@auth_required("Driver")
def complete(rid):
    route = db.delivery_routes.get(rid)
    if route is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"DeliveryRoute {rid} not found.")
    if route["status"] != "IN_TRANSIT":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only IN_TRANSIT routes may be completed.")
    _ensure_driver_match(route)

    now = clock.now()
    route["status"] = "COMPLETED"
    route["completed_at"] = now
    helpers.bump(route)

    vehicle = db.vehicles[route["vehicle_id"]]
    vehicle["status"] = "AVAILABLE"
    helpers.bump(vehicle)

    # Per stop: create one InventoryBatch per loaded batch at the receiving store,
    # transition each linked StoreOrder CONSOLIDATED -> DELIVERED.
    created_batches = []
    delivered_orders = set()
    for stop in route["planned_stops"]:
        store_id = stop["store_id"]
        for bid in stop["batch_ids"]:
            pbatch = db.production_batches[bid]
            recipe = db.recipes[pbatch["recipe_id"]]

            inv_id = db.new_id()
            common = helpers.common_create()
            inv = {
                "id": inv_id,
                "store_id": store_id,
                "recipe_id": recipe["id"],
                "production_batch_id": pbatch["id"],
                "quantity_on_hand": pbatch["planned_units"],
                "received_at": now,
                "expires_at": pbatch["expires_at"],
                "alert_tier": "NONE",
                "status": "ON_HAND",
                **common,
            }
            db.inventory_batches[inv_id] = inv
            created_batches.append(inv)
            audit.append(target_type="InventoryBatch", target_id=inv_id, action="RECEIVE_STOCK",
                         payload={"production_batch_id": pbatch["id"],
                                  "store_id": store_id,
                                  "quantity_on_hand": inv["quantity_on_hand"]})

            # Transition CONSOLIDATED orders for this batch + store to DELIVERED.
            for order in db.store_orders.values():
                if order["consolidation_batch_id"] != pbatch["id"]:
                    continue
                if order["store_id"] != store_id:
                    continue
                if order["status"] != "CONSOLIDATED":
                    continue
                order["status"] = "DELIVERED"
                helpers.bump(order)
                delivered_orders.add(order["id"])
                audit.append(target_type="StoreOrder", target_id=order["id"], action="DELIVER_ORDER",
                             payload={"production_batch_id": pbatch["id"]})

    audit.append(target_type="DeliveryRoute", target_id=rid, action="COMPLETE_ROUTE",
                 payload={"completed_at": clock.iso_format(now),
                          "inventory_batch_ids": [b["id"] for b in created_batches],
                          "delivered_order_ids": list(delivered_orders)},
                 external_systems=["LOGISTICS", "POS"])
    audit.append(target_type="Vehicle", target_id=vehicle["id"], action="VEHICLE_RELEASED",
                 payload={"route_id": rid})
    return response.ok(serializers.delivery_route_dict(route))


@bp.route("/<rid>/raise-exception", methods=["POST"])
@auth_required("Driver")
def raise_exception(rid):
    route = db.delivery_routes.get(rid)
    if route is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"DeliveryRoute {rid} not found.")
    if route["status"] != "IN_TRANSIT":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only IN_TRANSIT routes may raise exceptions.")
    _ensure_driver_match(route)

    body = helpers.get_json_body()
    reason = body.get("exception_reason")
    if not reason or not isinstance(reason, str):
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "exception_reason is required.")

    route["status"] = "EXCEPTION"
    route["exception_reason"] = reason
    helpers.bump(route)
    audit.append(target_type="DeliveryRoute", target_id=rid, action="RAISE_EXCEPTION",
                 payload={"exception_reason": reason},
                 external_systems=["LOGISTICS"])
    return response.ok(serializers.delivery_route_dict(route))


@bp.route("/<rid>/reroute", methods=["POST"])
@auth_required("CentralKitchenPlanner")
def reroute(rid):
    route = db.delivery_routes.get(rid)
    if route is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"DeliveryRoute {rid} not found.")
    if route["status"] != "EXCEPTION":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only EXCEPTION routes may be rerouted.")
    body = helpers.get_json_body()
    rep_id = body.get("replacement_vehicle_id")
    if not rep_id:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "replacement_vehicle_id is required.")

    replacement = db.vehicles.get(rep_id)
    if replacement is None:
        errors.raise_error(errors.ERR_REFERENCE_NOT_FOUND, "Replacement vehicle not found.")

    # Temperature zone check first.
    if not set(route["required_zones"]).issubset(set(replacement["temperature_zones"])):
        errors.raise_error(errors.ERR_TEMPERATURE_ZONE_INCOMPATIBLE,
                           "Replacement vehicle does not satisfy required zones.")
    if route["total_units_loaded"] > replacement["capacity_units"]:
        errors.raise_error(errors.ERR_VEHICLE_CAPACITY_EXCEEDED,
                           "Replacement vehicle capacity exceeded.")
    if replacement["status"] != "AVAILABLE":
        errors.raise_error(errors.ERR_VEHICLE_NOT_AVAILABLE,
                           "Replacement vehicle is not AVAILABLE.")

    # Original vehicle: ASSIGNED -> AVAILABLE.
    original = db.vehicles.get(route["vehicle_id"])
    if original is not None:
        original["status"] = "AVAILABLE"
        helpers.bump(original)
        audit.append(target_type="Vehicle", target_id=original["id"], action="VEHICLE_RELEASED",
                     payload={"route_id": rid, "via": "REROUTE"})
    replacement["status"] = "ASSIGNED"
    helpers.bump(replacement)
    audit.append(target_type="Vehicle", target_id=replacement["id"], action="VEHICLE_ASSIGNED",
                 payload={"route_id": rid, "via": "REROUTE"})

    route["vehicle_id"] = replacement["id"]
    route["status"] = "REROUTED"
    helpers.bump(route)
    audit.append(target_type="DeliveryRoute", target_id=rid, action="EXCEPTION_REROUTE",
                 payload={"replacement_vehicle_id": replacement["id"]},
                 external_systems=["LOGISTICS"])
    return response.ok(serializers.delivery_route_dict(route))
