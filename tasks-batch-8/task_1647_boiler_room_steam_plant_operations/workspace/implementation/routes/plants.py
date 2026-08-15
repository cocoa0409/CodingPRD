"""Plant endpoints, the operations checkpoint, and the logical clock."""
from flask import Blueprint

import clock
import resolve
import store
from auth import authenticate, authorize
from services import STATE_CODES, plant_json, run_ops
from util import (
    body_json,
    fmt_ts,
    new_record,
    req_dt,
    req_enum,
    req_num,
    req_str,
    success_object,
)

bp = Blueprint("plants", __name__)


@bp.post("/plants")
def create_plant():
    _, role = authenticate()
    authorize(role, ["PlantManager"])
    body = body_json()
    name = req_str(body, "name")
    state_code = req_enum(body, "state_code", STATE_CODES)
    header_pressure_psi = req_num(body, "header_pressure_psi")
    rec = new_record()
    rec.update({
        "name": name,
        "state_code": state_code,
        "header_pressure_psi": header_pressure_psi,
        "header_pressure_actual_psi": 0,
        "fuel_inventory_gal": 0,
        "total_fuel_received_gal": 0,
        "total_fuel_consumed_gal": 0,
        "posture": "NORMAL",
        "lead_boiler_id": None,
        "ops_run_index": 0,
    })
    store.plants[rec["id"]] = rec
    return success_object(plant_json(rec), 201)


@bp.get("/plants/<plantId>")
def get_plant(plantId):
    _, role = authenticate()
    authorize(role, ["PlantManager", "Operator", "Inspector"])
    rec = resolve.plant(plantId)
    return success_object(plant_json(rec))


@bp.post("/plants/<plantId>/run-ops")
def post_run_ops(plantId):
    _, role = authenticate()
    authorize(role, ["PlantManager"])
    rec = resolve.plant(plantId)
    run_ops(rec)
    return success_object(plant_json(rec))


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    authorize(role, ["PlantManager"])
    body = body_json()
    target = req_dt(body, "to_iso8601")
    clock.set_current(target)
    return success_object({"current_utc": fmt_ts(clock.now())})
