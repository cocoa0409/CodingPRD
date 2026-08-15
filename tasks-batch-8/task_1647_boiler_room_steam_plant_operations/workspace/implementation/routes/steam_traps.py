"""SteamTrap endpoints: registration, surveys (condition-driven leak rate),
and the computed loss-projection read (Napier default / Grashof for NY)."""
from flask import Blueprint, request

import clock
import resolve
import store
from auth import authenticate, authorize
from errors import raise_err, ERR_DUPLICATE_TAG
from services import (
    TRAP_CONDITIONS,
    require_active_operator,
    trap_json,
    trap_leak_rate,
    trap_loss_projection,
    traps_of,
)
from util import (
    body_json,
    list_response,
    new_record,
    req_enum,
    req_num,
    req_str,
    success_object,
    touch,
)

bp = Blueprint("steam_traps", __name__)

WRITERS = ["PlantManager", "Operator"]
READERS = ["PlantManager", "Operator"]


@bp.post("/plants/<plantId>/steam-traps")
def create_steam_trap(plantId):
    _, role = authenticate()
    authorize(role, WRITERS)
    plant = resolve.plant(plantId)
    body = body_json()
    tag = req_str(body, "tag")
    location = req_str(body, "location")
    orifice = req_num(body, "orifice_diameter_in")
    design_pressure = req_num(body, "design_pressure_psi")
    for t in traps_of(plant["id"]):
        if t["tag"] == tag:
            raise_err(ERR_DUPLICATE_TAG, "SteamTrap tag already exists within plant: %s" % tag)
    rec = new_record()
    rec.update({
        "plant_id": plant["id"],
        "tag": tag,
        "location": location,
        "orifice_diameter_in": orifice,
        "design_pressure_psi": design_pressure,
        "last_surveyed_at": None,
        "condition": "UNKNOWN",
        "leak_rate_lb_hr": 0,
        "status": "IN_SERVICE",
    })
    store.steam_traps[rec["id"]] = rec
    return success_object(trap_json(rec), 201)


@bp.get("/plants/<plantId>/steam-traps/<trapId>")
def get_steam_trap(plantId, trapId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    rec = resolve.steam_trap(plant, trapId)
    return success_object(trap_json(rec))


@bp.get("/plants/<plantId>/steam-traps")
def list_steam_traps(plantId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    recs = traps_of(plant["id"])
    condition = request.args.get("condition")
    status = request.args.get("status")
    if condition is not None:
        recs = [t for t in recs if t["condition"] == condition]
    if status is not None:
        recs = [t for t in recs if t["status"] == status]
    return list_response(recs, trap_json)


@bp.post("/plants/<plantId>/steam-traps/<trapId>/survey")
def survey_steam_trap(plantId, trapId):
    uid, role = authenticate()
    authorize(role, ["Operator"])
    plant = resolve.plant(plantId)
    trap = resolve.steam_trap(plant, trapId)
    body = body_json()
    condition = req_enum(body, "condition", TRAP_CONDITIONS)
    # license(8): an operator-initiated state change requires an ACTIVE license
    require_active_operator(uid)
    trap["condition"] = condition
    trap["last_surveyed_at"] = clock.now()
    if condition in ("LEAKING", "FAILED_OPEN"):
        trap["leak_rate_lb_hr"] = trap_leak_rate(plant, trap)
    else:
        trap["leak_rate_lb_hr"] = 0
    touch(trap)
    return success_object(trap_json(trap))


@bp.get("/plants/<plantId>/steam-traps/<trapId>/loss-projection")
def loss_projection(plantId, trapId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    trap = resolve.steam_trap(plant, trapId)
    return success_object(trap_loss_projection(plant, trap))
