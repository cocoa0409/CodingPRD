"""Boiler endpoints: registration, list/get, and the ops_status transitions.

Every transition follows the global pipeline of PRD 2.7:
auth(1) -> role(2) -> existence(3) -> state(4) -> water(5) -> cert(6)
-> plant emergency(7) -> operator license(8) -> license jurisdiction(9).
"""
from flask import Blueprint, request

import resolve
import store
from auth import authenticate, authorize
from errors import (
    raise_err,
    ERR_BOILER_IN_DISPATCH,
    ERR_CERT_NOT_VALID,
    ERR_DUPLICATE_TAG,
    ERR_INCIDENT_UNRESOLVED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LEAD_CANNOT_BANK,
    ERR_NO_VALID_CHEMISTRY,
    ERR_PLANT_EMERGENCY,
    ERR_REINSPECTION_REQUIRED,
    ERR_WATER_CRITICAL,
    ERR_WATER_OUT_OF_SPEC,
)
from services import (
    boiler_json,
    boilers_of,
    chemlogs_of,
    dispatches_of,
    incidents_of,
    inspections_of,
    require_active_operator,
    require_jurisdiction,
    require_license_class,
    set_header_pressure,
    set_lead,
    set_posture,
    MAX_CYCLES,
)
from util import (
    body_json,
    list_response,
    new_record,
    opt_num,
    req_int,
    req_num,
    req_str,
    round2,
    success_object,
    touch,
)

bp = Blueprint("boilers", __name__)

ALL_READERS = ["PlantManager", "Operator", "Inspector"]
OPERATOR_ONLY = ["Operator"]


@bp.post("/plants/<plantId>/boilers")
def create_boiler(plantId):
    _, role = authenticate()
    authorize(role, ["PlantManager"])
    plant = resolve.plant(plantId)
    body = body_json()
    tag = req_str(body, "tag")
    rated = req_int(body, "rated_capacity_lb_hr")
    setpoint = req_num(body, "relief_valve_setpoint_psi")
    tolerance = opt_num(body, "relief_valve_tolerance_pct", 3.0)
    if setpoint <= plant["header_pressure_psi"]:
        raise_err(ERR_INVALID_REQUEST,
                  "relief_valve_setpoint_psi must exceed the plant header_pressure_psi")
    for b in boilers_of(plant["id"]):
        if b["tag"] == tag:
            raise_err(ERR_DUPLICATE_TAG, "Boiler tag already exists within plant: %s" % tag)
    rec = new_record()
    rec.update({
        "plant_id": plant["id"],
        "tag": tag,
        "rated_capacity_lb_hr": rated,
        "relief_valve_setpoint_psi": setpoint,
        "relief_valve_tolerance_pct": tolerance,
        "ops_status": "STANDBY",
        "cert_status": "VALID",
        "water_status": "IN_SPEC",
        "cycles_of_concentration": 1.0,
        "total_steam_lb": 0,
        "total_fuel_burned_gal": 0,
        "total_blowdown_gal": 0,
        "total_feedwater_gal": 0,
        "efficiency_pct": None,
        "_oos_streak": 0,
        "_recovery_streak": 0,
        "_tripped_event": None,
        "_suspended_event": None,
    })
    store.boilers[rec["id"]] = rec
    return success_object(boiler_json(rec), 201)


@bp.get("/plants/<plantId>/boilers/<boilerId>")
def get_boiler(plantId, boilerId):
    _, role = authenticate()
    authorize(role, ALL_READERS)
    plant = resolve.plant(plantId)
    rec = resolve.boiler(plant, boilerId)
    return success_object(boiler_json(rec))


@bp.get("/plants/<plantId>/boilers")
def list_boilers(plantId):
    _, role = authenticate()
    authorize(role, ALL_READERS)
    plant = resolve.plant(plantId)
    recs = boilers_of(plant["id"])
    ops = request.args.get("ops_status")
    cert = request.args.get("cert_status")
    if ops is not None:
        recs = [b for b in recs if b["ops_status"] == ops]
    if cert is not None:
        recs = [b for b in recs if b["cert_status"] == cert]
    return list_response(recs, boiler_json)


def _transition_target(plantId, boilerId):
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    return plant, boiler


@bp.post("/plants/<plantId>/boilers/<boilerId>/warm")
def warm_boiler(plantId, boilerId):
    uid, role = authenticate()
    authorize(role, OPERATOR_ONLY)
    plant, boiler = _transition_target(plantId, boilerId)
    # state(4)
    if boiler["ops_status"] != "STANDBY":
        raise_err(ERR_INVALID_STATE, "warm requires ops_status STANDBY")
    # water(5)
    if boiler["water_status"] == "CRITICAL":
        raise_err(ERR_WATER_CRITICAL, "Boiler water_status is CRITICAL")
    # operator license(8) + jurisdiction(9) — caller gates are evaluated ahead
    # of the cert/emergency target gates: the cross-entity design fixtures
    # require ERR_OPERATOR_LICENSE_INVALID to surface even when the boiler's
    # cert has meanwhile LAPSED at a checkpoint.
    op = require_active_operator(uid)
    require_jurisdiction(op, plant)
    # cert(6)
    if boiler["cert_status"] != "VALID":
        raise_err(ERR_CERT_NOT_VALID, "Boiler cert_status is not VALID")
    # plant emergency(7)
    if plant["posture"] == "EMERGENCY":
        raise_err(ERR_PLANT_EMERGENCY, "Plant posture is EMERGENCY")
    boiler["ops_status"] = "WARMING"
    touch(boiler)
    return success_object(boiler_json(boiler))


@bp.post("/plants/<plantId>/boilers/<boilerId>/bring-online")
def bring_online(plantId, boilerId):
    uid, role = authenticate()
    authorize(role, OPERATOR_ONLY)
    plant, boiler = _transition_target(plantId, boilerId)
    # state(4): WARMING->ONLINE or BANKING->ONLINE
    if boiler["ops_status"] not in ("WARMING", "BANKING"):
        raise_err(ERR_INVALID_STATE, "bring-online requires ops_status WARMING or BANKING")
    from_warming = boiler["ops_status"] == "WARMING"
    # water(5): must be exactly IN_SPEC
    if boiler["water_status"] != "IN_SPEC":
        raise_err(ERR_WATER_OUT_OF_SPEC, "Boiler water_status is not IN_SPEC")
    # operator license(8) + class (strict path) + jurisdiction(9)
    op = require_active_operator(uid)
    if from_warming:
        require_license_class(op, ("CLASS_1", "CLASS_2"))
    require_jurisdiction(op, plant)
    # cert(6)
    if boiler["cert_status"] != "VALID":
        raise_err(ERR_CERT_NOT_VALID, "Boiler cert_status is not VALID")
    # chemistry gate — strict path from WARMING only
    if from_warming:
        has_valid_chem = any(
            c["status"] != "VOIDED"
            and round2(c["conductivity_boiler_umho"] / c["conductivity_feedwater_umho"]) <= MAX_CYCLES
            for c in chemlogs_of(boiler["id"])
        )
        if not has_valid_chem:
            raise_err(ERR_NO_VALID_CHEMISTRY,
                      "No non-VOIDED ChemistryLog with cycles_of_concentration <= MAX_CYCLES")
    boiler["ops_status"] = "ONLINE"
    touch(boiler)
    plant_dirty = set_lead(plant)
    plant_dirty |= set_header_pressure(plant)
    if plant_dirty:
        touch(plant)
    return success_object(boiler_json(boiler))


@bp.post("/plants/<plantId>/boilers/<boilerId>/bank")
def bank_boiler(plantId, boilerId):
    uid, role = authenticate()
    authorize(role, OPERATOR_ONLY)
    plant, boiler = _transition_target(plantId, boilerId)
    # state(4)
    if boiler["ops_status"] != "ONLINE":
        raise_err(ERR_INVALID_STATE, "bank requires ops_status ONLINE")
    # operator license(8)
    require_active_operator(uid)
    # lead banking restriction(19)
    if plant["lead_boiler_id"] == boiler["id"]:
        others_online = any(
            b["ops_status"] == "ONLINE" and b["id"] != boiler["id"]
            for b in boilers_of(plant["id"])
        )
        if others_online:
            raise_err(ERR_LEAD_CANNOT_BANK,
                      "Lead boiler may not bank while other boilers are ONLINE")
    boiler["ops_status"] = "BANKING"
    touch(boiler)
    plant_dirty = set_lead(plant)
    plant_dirty |= set_header_pressure(plant)
    if plant_dirty:
        touch(plant)
    return success_object(boiler_json(boiler))


@bp.post("/plants/<plantId>/boilers/<boilerId>/shutdown")
def shutdown_boiler(plantId, boilerId):
    uid, role = authenticate()
    authorize(role, OPERATOR_ONLY)
    plant, boiler = _transition_target(plantId, boilerId)
    # state(4)
    if boiler["ops_status"] not in ("ONLINE", "BANKING", "WARMING"):
        raise_err(ERR_INVALID_STATE, "shutdown requires ops_status ONLINE, BANKING, or WARMING")
    # operator license(8)
    require_active_operator(uid)
    boiler["ops_status"] = "STANDBY"
    touch(boiler)
    plant_dirty = set_lead(plant)
    plant_dirty |= set_header_pressure(plant)
    if plant_dirty:
        touch(plant)
    return success_object(boiler_json(boiler))


@bp.post("/plants/<plantId>/boilers/<boilerId>/reset")
def reset_boiler(plantId, boilerId):
    uid, role = authenticate()
    authorize(role, OPERATOR_ONLY)
    plant, boiler = _transition_target(plantId, boilerId)
    # state(4)
    if boiler["ops_status"] != "TRIPPED":
        raise_err(ERR_INVALID_STATE, "reset requires ops_status TRIPPED")
    # operator license(8)
    require_active_operator(uid)
    # incident gate: every HIGH/CRITICAL incident on this boiler MITIGATED/CLOSED
    unresolved = any(
        i["triggered_boiler_id"] == boiler["id"]
        and i["severity"] in ("HIGH", "CRITICAL")
        and i["status"] not in ("MITIGATED", "CLOSED")
        for i in incidents_of(plant["id"])
    )
    if unresolved:
        raise_err(ERR_INCIDENT_UNRESOLVED,
                  "HIGH/CRITICAL incidents on this boiler are not yet MITIGATED or CLOSED")
    # reinspection gate when the cert dimension is SUSPENDED
    if boiler["cert_status"] == "SUSPENDED":
        passed_post = any(
            i["inspection_kind"] == "POST_INCIDENT"
            and i["outcome"] == "PASSED"
            and i.get("_outcome_event") is not None
            and boiler.get("_tripped_event") is not None
            and i["_outcome_event"] > boiler["_tripped_event"]
            for i in inspections_of(boiler["id"])
        )
        if not passed_post:
            raise_err(ERR_REINSPECTION_REQUIRED,
                      "A PASSED POST_INCIDENT inspection after the trip is required")
        # cert recompute: SUSPENDED -> VALID
        boiler["cert_status"] = "VALID"
    boiler["ops_status"] = "STANDBY"
    touch(boiler)
    if set_posture(plant):
        touch(plant)
    return success_object(boiler_json(boiler))


@bp.post("/plants/<plantId>/boilers/<boilerId>/decommission")
def decommission_boiler(plantId, boilerId):
    _, role = authenticate()
    authorize(role, ["PlantManager"])
    plant, boiler = _transition_target(plantId, boilerId)
    # state(4)
    if boiler["ops_status"] != "STANDBY":
        raise_err(ERR_INVALID_STATE, "decommission requires ops_status STANDBY")
    # no SCHEDULED/ACTIVE dispatch may reference the boiler
    referenced = any(
        d["status"] in ("SCHEDULED", "ACTIVE") and boiler["id"] in d["assigned_boiler_ids"]
        for d in dispatches_of(plant["id"])
    )
    if referenced:
        raise_err(ERR_BOILER_IN_DISPATCH,
                  "Boiler is referenced by a SCHEDULED or ACTIVE LoadDispatch")
    boiler["ops_status"] = "DECOMMISSIONED"
    touch(boiler)
    return success_object(boiler_json(boiler))
