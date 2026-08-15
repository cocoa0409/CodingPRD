"""CollectionRoute and RouteStop endpoints."""
from flask import Blueprint, request

import db
from common import (caller, require_role, body_json, v_str, v_int, v_num,
                    v_enum, v_bool, v_date, v_datetime, ok, view, stamp_new,
                    touch, paginate, sorted_items, get_or_404, fail, iso_z,
                    parse_dt)
from logic import (posture_gate, current_settlement, batch_for_stop,
                   stops_of_route, provisional_fee, final_fee,
                   windows_overlap, cancel_route_system,
                   supplier_suspend_cascade, TRANSPORT_COST_PER_MILE_CENTS,
                   STOP_TERMINAL)

bp = Blueprint("logistics", __name__)

SPECIES_ALL = {"BOVINE", "PORCINE", "POULTRY", "OVINE", "MIXED"}
REJECTION_REASONS = {"PROHIBITED_MATERIAL", "TEMPERATURE_EXCURSION", "OTHER"}


# ---------------- collection routes ----------------

@bp.post("/rendering/collection-routes")
def create_route():
    uid, role = caller()
    b = body_json()
    plant_id = v_str(b, "plant_id")
    vehicle_id = v_str(b, "vehicle_id")
    route_code = v_str(b, "route_code")
    service_date = v_date(b, "service_date")
    dep = v_datetime(b, "scheduled_departure", whole_hour=True)
    ret = v_datetime(b, "scheduled_return", whole_hour=True)
    dep_dt = parse_dt(dep)
    ret_dt = parse_dt(ret)
    if ret_dt <= dep_dt:
        fail("ERR_INVALID_REQUEST", 400, "scheduled_return must be strictly after scheduled_departure")
    require_role(role, "RouteDispatcher")
    plant = get_or_404("plants", plant_id, "ERR_PLANT_NOT_FOUND")
    vehicle = get_or_404("vehicles", vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    posture_gate(plant, "op")
    if vehicle["sanitation_status"] != "SANITIZED":
        fail("ERR_VEHICLE_NOT_SANITIZED", 409, "Vehicle must be SANITIZED")
    if vehicle["duty_class"] not in ("RAW_MATERIAL", "DUAL"):
        fail("ERR_VEHICLE_DUTY_MISMATCH", 409, "Vehicle duty must be RAW_MATERIAL or DUAL")
    for r in db.STORES["routes"].values():
        if (r["vehicle_id"] == vehicle_id
                and r["status"] in ("PLANNED", "DISPATCHED", "IN_PROGRESS")
                and windows_overlap(dep_dt, ret_dt, r["_dep"], r["_ret"])):
            fail("ERR_VEHICLE_SCHEDULE_OVERLAP", 409,
                 "Vehicle already has a route overlapping this window")
    route = {
        "plant_id": plant_id,
        "vehicle_id": vehicle_id,
        "route_code": route_code,
        "service_date": service_date,
        "scheduled_departure": dep,
        "scheduled_return": ret,
        "_dep": dep_dt,
        "_ret": ret_dt,
        "total_collected_lbs": 0,
        "status": "PLANNED",
    }
    stamp_new(route)
    db.STORES["routes"][route["id"]] = route
    return ok(view(route), 201)


@bp.get("/rendering/collection-routes")
def list_routes():
    caller()
    items = sorted_items("routes", {
        "plant_id": request.args.get("plant_id"),
        "vehicle_id": request.args.get("vehicle_id"),
        "status": request.args.get("status"),
        "service_date": request.args.get("service_date"),
    })
    return paginate(items)


@bp.get("/rendering/collection-routes/<rid>")
def get_route(rid):
    caller()
    return ok(view(get_or_404("routes", rid, "ERR_ROUTE_NOT_FOUND")), 200)


@bp.post("/rendering/collection-routes/<rid>/dispatch")
def dispatch_route(rid):
    uid, role = caller()
    require_role(role, "RouteDispatcher")
    route = get_or_404("routes", rid, "ERR_ROUTE_NOT_FOUND")
    plant = get_or_404("plants", route["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "dispatch")
    if route["status"] != "PLANNED":
        fail("ERR_ROUTE_INVALID_STATE", 409, "Route must be PLANNED to dispatch")
    vehicle = get_or_404("vehicles", route["vehicle_id"], "ERR_VEHICLE_NOT_FOUND")
    if vehicle["sanitation_status"] != "SANITIZED":
        fail("ERR_VEHICLE_NOT_SANITIZED", 409, "Vehicle must be SANITIZED")
    if vehicle["duty_class"] not in ("RAW_MATERIAL", "DUAL"):
        fail("ERR_VEHICLE_DUTY_MISMATCH", 409, "Vehicle duty must be RAW_MATERIAL or DUAL")
    live_stops = [s for s in stops_of_route(rid) if s["status"] != "CANCELLED"]
    if len(live_stops) == 0:
        fail("ERR_ROUTE_EMPTY", 422, "Route has no non-CANCELLED stops")
    if db.now() > route["_ret"]:
        fail("ERR_ROUTE_WINDOW_PASSED", 422, "Current logical time is past scheduled_return")
    for s in live_stops:
        ag = db.STORES["agreements"].get(s["agreement_id"])
        if ag is not None and not (ag["effective_from"] <= route["service_date"] <= ag["effective_to"]):
            fail("ERR_AGREEMENT_NOT_IN_EFFECT", 422,
                 "Route service_date lies outside a stop's agreement window")
    route["status"] = "DISPATCHED"
    touch(route)
    return ok(view(route), 200)


@bp.post("/rendering/collection-routes/<rid>/complete")
def complete_route(rid):
    uid, role = caller()
    require_role(role, "RouteDispatcher")
    route = get_or_404("routes", rid, "ERR_ROUTE_NOT_FOUND")
    plant = get_or_404("plants", route["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "op")
    if route["status"] not in ("DISPATCHED", "IN_PROGRESS"):
        fail("ERR_ROUTE_INVALID_STATE", 409, "Route must be DISPATCHED or IN_PROGRESS to complete")
    stops = stops_of_route(rid)
    for s in stops:
        if s["status"] not in STOP_TERMINAL:
            fail("ERR_STOP_INVALID_STATE", 409, "Every stop must be in a terminal state to complete")
    route["status"] = "COMPLETED"
    route["total_collected_lbs"] = sum(
        s["actual_weight_lbs"] or 0 for s in stops if s["status"] in ("DELIVERED", "VOIDED"))
    touch(route)
    vehicle = db.STORES["vehicles"].get(route["vehicle_id"])
    if vehicle is not None:
        vehicle["sanitation_status"] = "DIRTY"
        vehicle["completed_trip_count"] += 1
        touch(vehicle)
    return ok(view(route), 200)


@bp.post("/rendering/collection-routes/<rid>/cancel")
def cancel_route(rid):
    uid, role = caller()
    require_role(role, "RouteDispatcher")
    route = get_or_404("routes", rid, "ERR_ROUTE_NOT_FOUND")
    plant = get_or_404("plants", route["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "op")
    if route["status"] not in ("PLANNED", "DISPATCHED", "IN_PROGRESS"):
        fail("ERR_ROUTE_INVALID_STATE", 409, "Route must be PLANNED, DISPATCHED or IN_PROGRESS to cancel")
    for s in stops_of_route(rid):
        if s["status"] == "COLLECTED":
            fail("ERR_ROUTE_HAS_COLLECTED_STOPS", 409,
                 "Route has COLLECTED stops; deliver or void them first")
    for s in stops_of_route(rid):
        if s["status"] in ("SCHEDULED", "ARRIVED"):
            s["status"] = "CANCELLED"
            touch(s)
    route["status"] = "CANCELLED"
    touch(route)
    return ok(view(route), 200)


# ---------------- route stops ----------------

@bp.post("/rendering/route-stops")
def create_stop():
    uid, role = caller()
    b = body_json()
    route_id = v_str(b, "route_id")
    supplier_id = v_str(b, "supplier_id")
    agreement_id = v_str(b, "agreement_id")
    plant_id = v_str(b, "plant_id")
    seq_no = v_int(b, "sequence_no", minv=1)
    w_start = v_datetime(b, "scheduled_window_start")
    w_end = v_datetime(b, "scheduled_window_end")
    ws_dt = parse_dt(w_start)
    we_dt = parse_dt(w_end)
    if we_dt <= ws_dt:
        fail("ERR_INVALID_REQUEST", 400, "scheduled_window_end must be strictly after scheduled_window_start")
    est_weight = v_int(b, "estimated_weight_lbs", minv=1)
    est_miles = v_int(b, "estimated_distance_miles", minv=0)
    species_tag = v_enum(b, "species_tag", SPECIES_ALL)
    is_dead = v_bool(b, "is_dead_stock")
    expected_route_version = v_int(b, "expected_route_version")
    require_role(role, "RouteDispatcher")
    # existence, left-to-right in declared body order
    route = get_or_404("routes", route_id, "ERR_ROUTE_NOT_FOUND")
    supplier = get_or_404("suppliers", supplier_id, "ERR_SUPPLIER_NOT_FOUND")
    agreement = get_or_404("agreements", agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    plant = get_or_404("plants", plant_id, "ERR_PLANT_NOT_FOUND")
    if route["plant_id"] != plant_id:
        fail("ERR_INVALID_REQUEST", 400, "plant_id must equal the route's plant")
    posture_gate(plant, "op")
    if route["status"] != "PLANNED":
        fail("ERR_ROUTE_INVALID_STATE", 409, "Stops may only be added to a PLANNED route")
    if route["version"] != expected_route_version:
        fail("ERR_STALE_VERSION", 412, "expected_route_version does not match the route's current version")
    # species & sourcing compliance (priority 9)
    if species_tag not in agreement["species_scope"]:
        fail("ERR_SPECIES_OUT_OF_SCOPE", 422, "species_tag is not in the agreement's species_scope")
    if is_dead and not agreement["accepts_dead_stock"]:
        fail("ERR_DEAD_STOCK_NOT_ACCEPTED", 422, "Agreement does not accept dead stock")
    # cross-entity state (priority 11)
    if supplier["status"] != "ACTIVE":
        fail("ERR_SUPPLIER_NOT_ACTIVE", 409, "Supplier must be ACTIVE")
    if agreement["status"] != "ACTIVE" or agreement["supplier_id"] != supplier_id:
        fail("ERR_AGREEMENT_NOT_ACTIVE", 409, "Agreement must be ACTIVE and belong to the supplier")
    # capacity (priority 13)
    vehicle = db.STORES["vehicles"].get(route["vehicle_id"])
    planned_load = est_weight + sum(
        s["estimated_weight_lbs"] for s in stops_of_route(route_id)
        if s["status"] in ("SCHEDULED", "ARRIVED"))
    if vehicle is not None and planned_load > vehicle["capacity_lbs"]:
        fail("ERR_ROUTE_OVER_CAPACITY", 422, "Planned load exceeds vehicle capacity")
    for s in stops_of_route(route_id):
        if s["status"] != "CANCELLED" and s["sequence_no"] == seq_no:
            fail("ERR_DUPLICATE_STOP_SEQUENCE", 422, "sequence_no already used on this route")
    # temporal windows (priority 15)
    if ws_dt < route["_dep"] or we_dt > route["_ret"]:
        fail("ERR_WINDOW_OUTSIDE_ROUTE", 422, "Stop window must lie within the route window")
    if not (agreement["effective_from"] <= route["service_date"] <= agreement["effective_to"]):
        fail("ERR_AGREEMENT_NOT_IN_EFFECT", 422, "Route service_date outside the agreement window")
    stop = {
        "route_id": route_id,
        "supplier_id": supplier_id,
        "agreement_id": agreement_id,
        "plant_id": plant_id,
        "sequence_no": seq_no,
        "scheduled_window_start": w_start,
        "scheduled_window_end": w_end,
        "estimated_weight_lbs": est_weight,
        "estimated_distance_miles": est_miles,
        "species_tag": species_tag,
        "is_dead_stock": is_dead,
        "actual_weight_lbs": None,
        "actual_distance_miles": None,
        "provisional_fee_cents": provisional_fee(agreement, est_weight, est_miles, is_dead),
        "final_fee_cents": None,
        "rejection_reason": None,
        "status": "SCHEDULED",
        "_collected_period": None,
    }
    stamp_new(stop)
    db.STORES["stops"][stop["id"]] = stop
    touch(route)
    return ok(view(stop), 201)


@bp.get("/rendering/route-stops")
def list_stops():
    caller()
    items = sorted_items("stops", {
        "route_id": request.args.get("route_id"),
        "supplier_id": request.args.get("supplier_id"),
        "agreement_id": request.args.get("agreement_id"),
        "plant_id": request.args.get("plant_id"),
        "status": request.args.get("status"),
    })
    return paginate(items)


@bp.get("/rendering/route-stops/<sid>")
def get_stop(sid):
    caller()
    return ok(view(get_or_404("stops", sid, "ERR_STOP_NOT_FOUND")), 200)


def _stop_ctx(sid):
    stop = get_or_404("stops", sid, "ERR_STOP_NOT_FOUND")
    plant = get_or_404("plants", stop["plant_id"], "ERR_PLANT_NOT_FOUND")
    route = get_or_404("routes", stop["route_id"], "ERR_ROUTE_NOT_FOUND")
    return stop, plant, route


@bp.post("/rendering/route-stops/<sid>/arrive")
def arrive_stop(sid):
    uid, role = caller()
    require_role(role, "RouteDispatcher")
    stop, plant, route = _stop_ctx(sid)
    posture_gate(plant, "op")
    if stop["status"] != "SCHEDULED":
        fail("ERR_STOP_INVALID_STATE", 409, "Stop must be SCHEDULED to arrive")
    if route["status"] not in ("DISPATCHED", "IN_PROGRESS"):
        fail("ERR_ROUTE_INVALID_STATE", 409, "Route must be DISPATCHED or IN_PROGRESS")
    stop["status"] = "ARRIVED"
    touch(stop)
    if route["status"] == "DISPATCHED":
        route["status"] = "IN_PROGRESS"
        touch(route)
    return ok(view(stop), 200)


@bp.post("/rendering/route-stops/<sid>/collect")
def collect_stop(sid):
    uid, role = caller()
    b = body_json()
    act_weight = v_int(b, "actual_weight_lbs", minv=1)
    act_miles = v_int(b, "actual_distance_miles", minv=0)
    temp = v_num(b, "temperature_f")
    require_role(role, "RouteDispatcher")
    stop, plant, route = _stop_ctx(sid)
    posture_gate(plant, "op")
    if stop["status"] != "ARRIVED":
        fail("ERR_STOP_INVALID_STATE", 409, "Stop must be ARRIVED to collect")
    settlement = current_settlement(plant)
    if settlement is None or settlement["status"] not in ("OPEN", "REOPENED"):
        fail("ERR_PERIOD_CLOSED", 409, "Current period settlement is not OPEN/REOPENED")
    agreement = db.STORES["agreements"].get(stop["agreement_id"])
    fee = final_fee(agreement, stop, act_weight, act_miles, plant)
    stop["actual_weight_lbs"] = act_weight
    stop["actual_distance_miles"] = act_miles
    stop["final_fee_cents"] = fee
    stop["status"] = "COLLECTED"
    stop["_collected_period"] = plant["current_period_index"]
    touch(stop)
    batch = {
        "plant_id": plant["id"],
        "supplier_id": stop["supplier_id"],
        "agreement_id": stop["agreement_id"],
        "route_stop_id": stop["id"],
        "species": stop["species_tag"],
        "weight_lbs": act_weight,
        "temperature_f": temp,
        "received_at": iso_z(db.now()),
        "screening_result": "PENDING",
        "screened_by": None,
        "reserved_lbs": 0,
        "consumed_lbs": 0,
        "status": "RECEIVED",
    }
    stamp_new(batch)
    db.STORES["batches"][batch["id"]] = batch
    settlement["pickup_fees_accrued_cents"] += fee
    settlement["transport_costs_cents"] += act_miles * TRANSPORT_COST_PER_MILE_CENTS
    touch(settlement)
    supplier = db.STORES["suppliers"].get(stop["supplier_id"])
    if supplier is not None:
        supplier["outstanding_service_fees_cents"] += fee
        touch(supplier)
    return ok(view(stop), 201)


@bp.post("/rendering/route-stops/<sid>/reject-at-site")
def reject_stop(sid):
    uid, role = caller()
    b = body_json()
    reason = v_enum(b, "rejection_reason", REJECTION_REASONS)
    require_role(role, "RouteDispatcher")
    stop, plant, route = _stop_ctx(sid)
    posture_gate(plant, "op")
    if stop["status"] != "ARRIVED":
        fail("ERR_STOP_INVALID_STATE", 409, "Stop must be ARRIVED to reject at site")
    stop["status"] = "REJECTED_AT_SITE"
    stop["rejection_reason"] = reason
    touch(stop)
    if reason == "PROHIBITED_MATERIAL":
        supplier = db.STORES["suppliers"].get(stop["supplier_id"])
        if supplier is not None and supplier["status"] == "ACTIVE":
            supplier["contamination_strikes"] += 1
            touch(supplier)
            if supplier["contamination_strikes"] >= 3:
                supplier_suspend_cascade(supplier)
    return ok(view(stop), 200)


@bp.post("/rendering/route-stops/<sid>/miss")
def miss_stop(sid):
    uid, role = caller()
    require_role(role, "RouteDispatcher")
    stop, plant, route = _stop_ctx(sid)
    posture_gate(plant, "op")
    if stop["status"] != "SCHEDULED":
        fail("ERR_STOP_INVALID_STATE", 409, "Stop must be SCHEDULED to miss")
    if route["status"] not in ("DISPATCHED", "IN_PROGRESS"):
        fail("ERR_ROUTE_INVALID_STATE", 409, "Route must be DISPATCHED or IN_PROGRESS")
    stop["status"] = "MISSED"
    touch(stop)
    return ok(view(stop), 200)


@bp.post("/rendering/route-stops/<sid>/deliver")
def deliver_stop(sid):
    uid, role = caller()
    require_role(role, "RouteDispatcher")
    stop, plant, route = _stop_ctx(sid)
    posture_gate(plant, "op")
    if stop["status"] != "COLLECTED":
        fail("ERR_STOP_INVALID_STATE", 409, "Stop must be COLLECTED to deliver")
    stop["status"] = "DELIVERED"
    touch(stop)
    return ok(view(stop), 200)


@bp.post("/rendering/route-stops/<sid>/void")
def void_stop(sid):
    uid, role = caller()
    require_role(role, "RouteDispatcher")
    stop, plant, route = _stop_ctx(sid)
    posture_gate(plant, "op")
    if stop["status"] not in ("COLLECTED", "DELIVERED"):
        fail("ERR_STOP_INVALID_STATE", 409, "Stop must be COLLECTED or DELIVERED to void")
    batch = batch_for_stop(stop["id"])
    if batch is not None and (batch["reserved_lbs"] != 0 or batch["consumed_lbs"] != 0):
        fail("ERR_BATCH_INVALID_STATE", 409, "Linked batch has reserved or consumed pounds")
    settlement = current_settlement(plant)
    if (stop.get("_collected_period") != plant["current_period_index"]
            or settlement is None or settlement["status"] not in ("OPEN", "REOPENED")):
        fail("ERR_PERIOD_CLOSED", 409, "Current period settlement cannot accept the reversal")
    fee = stop["final_fee_cents"] or 0
    miles = stop["actual_distance_miles"] or 0
    settlement["pickup_fees_accrued_cents"] -= fee
    settlement["transport_costs_cents"] -= miles * TRANSPORT_COST_PER_MILE_CENTS
    touch(settlement)
    supplier = db.STORES["suppliers"].get(stop["supplier_id"])
    if supplier is not None:
        supplier["outstanding_service_fees_cents"] -= fee
        touch(supplier)
    if batch is not None:
        batch["status"] = "REJECTED"
        touch(batch)
    stop["status"] = "VOIDED"
    touch(stop)
    return ok(view(stop), 200)
