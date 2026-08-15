"""ChemistryLog endpoints: record (drives cycles, water_status cascades and
the 7-step blowdown chain), list/get, and the PlantManager-only void."""
from flask import Blueprint, request

import resolve
import store
from auth import authenticate, authorize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REFERENCED_NOT_FOUND,
)
from services import (
    apply_chemistry_log,
    chemlogs_of,
    chemistry_json,
    recompute_water_from_logs,
    require_active_operator,
    require_jurisdiction,
)
from util import (
    body_json,
    list_response,
    new_journal_record,
    req_dt,
    req_num,
    req_str,
    success_object,
    touch,
)

bp = Blueprint("chemistry", __name__)

READERS = ["PlantManager", "Operator"]


@bp.post("/plants/<plantId>/boilers/<boilerId>/chemistry-logs")
def create_chemistry_log(plantId, boilerId):
    uid, role = authenticate()
    authorize(role, ["Operator"])
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    body = body_json()
    recorded_by = req_str(body, "recorded_by_operator_id")
    recorded_at = req_dt(body, "recorded_at")
    cond_b = req_num(body, "conductivity_boiler_umho")
    cond_f = req_num(body, "conductivity_feedwater_umho")
    sulfite = req_num(body, "sulfite_residual_ppm")
    phosphate = req_num(body, "phosphate_residual_ppm")
    if cond_f <= 0:
        raise_err(ERR_INVALID_REQUEST, "conductivity_feedwater_umho must be greater than zero")
    # license(8) + jurisdiction(9) on the calling operator
    op = require_active_operator(uid)
    require_jurisdiction(op, plant)
    # referential integrity(11)
    if store.operators.get(recorded_by) is None:
        raise_err(ERR_REFERENCED_NOT_FOUND,
                  "recorded_by_operator_id does not reference an existing operator")
    rec = new_journal_record()
    rec.update({
        "boiler_id": boiler["id"],
        "recorded_by_operator_id": recorded_by,
        "recorded_at": recorded_at,
        "conductivity_boiler_umho": cond_b,
        "conductivity_feedwater_umho": cond_f,
        "sulfite_residual_ppm": sulfite,
        "phosphate_residual_ppm": phosphate,
        "status": "RECORDED",
    })
    store.chemistry_logs[rec["id"]] = rec
    apply_chemistry_log(plant, boiler, rec, uid)
    return success_object(chemistry_json(rec), 201)


@bp.get("/plants/<plantId>/boilers/<boilerId>/chemistry-logs/<logId>")
def get_chemistry_log(plantId, boilerId, logId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    rec = resolve.chemistry_log(boiler, logId)
    return success_object(chemistry_json(rec))


@bp.get("/plants/<plantId>/boilers/<boilerId>/chemistry-logs")
def list_chemistry_logs(plantId, boilerId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    recs = chemlogs_of(boiler["id"])
    status = request.args.get("status")
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return list_response(recs, chemistry_json)


@bp.post("/plants/<plantId>/boilers/<boilerId>/chemistry-logs/<logId>/void")
def void_chemistry_log(plantId, boilerId, logId):
    _, role = authenticate()
    authorize(role, ["PlantManager"])
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    rec = resolve.chemistry_log(boiler, logId)
    # state(4): RECORDED -> VOIDED only
    if rec["status"] != "RECORDED":
        raise_err(ERR_INVALID_STATE, "Only a RECORDED chemistry log can be voided")
    rec["status"] = "VOIDED"
    recompute_water_from_logs(boiler)
    touch(boiler)
    return success_object(chemistry_json(rec))
