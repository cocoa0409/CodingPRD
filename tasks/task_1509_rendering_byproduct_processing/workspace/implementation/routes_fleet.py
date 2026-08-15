"""Vehicle and WashTicket endpoints."""
from flask import Blueprint, request

import db
from common import (caller, require_role, body_json, v_str, v_int, v_num,
                    v_enum, v_datetime, ok, view, stamp_new, touch,
                    paginate, sorted_items, get_or_404, fail)
from logic import posture_gate

bp = Blueprint("fleet", __name__)

DUTY_CLASSES = {"RAW_MATERIAL", "FINISHED_PRODUCT", "DUAL"}


@bp.post("/rendering/vehicles")
def create_vehicle():
    uid, role = caller()
    b = body_json()
    plant_id = v_str(b, "plant_id")
    tag = v_str(b, "vehicle_tag")
    cap = v_int(b, "capacity_lbs", minv=1)
    duty = v_enum(b, "duty_class", DUTY_CLASSES)
    require_role(role, "RouteDispatcher")
    plant = get_or_404("plants", plant_id, "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    v = {
        "plant_id": plant_id,
        "vehicle_tag": tag,
        "capacity_lbs": cap,
        "duty_class": duty,
        "sanitation_status": "SANITIZED",
        "completed_trip_count": 0,
    }
    stamp_new(v)
    db.STORES["vehicles"][v["id"]] = v
    return ok(view(v), 201)


@bp.get("/rendering/vehicles")
def list_vehicles():
    caller()
    items = sorted_items("vehicles", {
        "plant_id": request.args.get("plant_id"),
        "sanitation_status": request.args.get("sanitation_status"),
        "duty_class": request.args.get("duty_class"),
    })
    return paginate(items)


@bp.get("/rendering/vehicles/<vid>")
def get_vehicle(vid):
    caller()
    return ok(view(get_or_404("vehicles", vid, "ERR_VEHICLE_NOT_FOUND")), 200)


@bp.post("/rendering/vehicles/<vid>/wash-tickets")
def create_wash_ticket(vid):
    uid, role = caller()
    b = body_json()
    plant_id = v_str(b, "plant_id")
    wash_type = v_enum(b, "wash_type", {"STANDARD", "DEEP"})
    washed_at = v_datetime(b, "washed_at")
    detergent = v_num(b, "detergent_ppm")
    result = v_enum(b, "result", {"PASS", "FAIL"})
    require_role(role, "RouteDispatcher")
    vehicle = get_or_404("vehicles", vid, "ERR_VEHICLE_NOT_FOUND")
    plant = get_or_404("plants", plant_id, "ERR_PLANT_NOT_FOUND")
    if vehicle["plant_id"] != plant_id:
        fail("ERR_INVALID_REQUEST", 400, "plant_id must equal the vehicle's plant")
    posture_gate(plant, "admin")
    if vehicle["sanitation_status"] == "QUARANTINED" and wash_type != "DEEP":
        fail("ERR_DEEP_WASH_REQUIRED", 422, "A QUARANTINED vehicle requires a DEEP wash")
    t = {
        "vehicle_id": vid,
        "plant_id": plant_id,
        "wash_type": wash_type,
        "washed_at": washed_at,
        "detergent_ppm": detergent,
        "result": result,
        "recorded_by": uid,
    }
    stamp_new(t, common=False)
    db.STORES["wash_tickets"][t["id"]] = t
    if result == "PASS" and vehicle["sanitation_status"] in ("DIRTY", "QUARANTINED"):
        vehicle["sanitation_status"] = "SANITIZED"
        touch(vehicle)
    return ok(view(t), 201)


@bp.get("/rendering/wash-tickets")
def list_wash_tickets():
    caller()
    items = sorted_items("wash_tickets", {
        "plant_id": request.args.get("plant_id"),
        "vehicle_id": request.args.get("vehicle_id"),
        "result": request.args.get("result"),
    })
    return paginate(items)


@bp.get("/rendering/wash-tickets/<tid>")
def get_wash_ticket(tid):
    caller()
    return ok(view(get_or_404("wash_tickets", tid, "ERR_WASH_TICKET_NOT_FOUND")), 200)


@bp.post("/rendering/vehicles/<vid>/quarantine")
def quarantine_vehicle(vid):
    uid, role = caller()
    require_role(role, "ComplianceOfficer")
    vehicle = get_or_404("vehicles", vid, "ERR_VEHICLE_NOT_FOUND")
    plant = get_or_404("plants", vehicle["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    if vehicle["sanitation_status"] == "QUARANTINED":
        fail("ERR_VEHICLE_INVALID_STATE", 409, "Vehicle is already QUARANTINED")
    vehicle["sanitation_status"] = "QUARANTINED"
    touch(vehicle)
    return ok(view(vehicle), 200)
