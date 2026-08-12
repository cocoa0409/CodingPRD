"""Stability chamber, study, and reading endpoints."""
from flask import Blueprint, g, request

from core import (body, check_enum, check_int, check_string, err, get_required,
                  list_page, new_entity, require_roles, success, touch)
from services import must_get, serialize_chamber, serialize_reading, serialize_study
from store import db, iso_now, new_id

bp = Blueprint("stability", __name__)


@bp.post("/cosmfg/stability-chambers")
@require_roles("QAManager")
def create_chamber():
    b = body()
    code = check_string(get_required(b, "chamber_code"), "chamber_code")
    for existing in db.chambers.values():
        if existing["chamber_code"] == code:
            err("ERR_VALIDATION", 400, "chamber_code must be unique")
    capacity = check_int(get_required(b, "capacity_studies"), "capacity_studies",
                         minimum=1)
    c = new_entity()
    c.update({
        "chamber_code": code,
        "capacity_studies": capacity,
        "active_study_count": 0,
    })
    db.chambers[c["id"]] = c
    return success(serialize_chamber(c), status=201)


@bp.get("/cosmfg/stability-chambers/<cid>")
@require_roles("QAManager", "PlantDirector", "ProductionPlanner")
def get_chamber(cid):
    return success(serialize_chamber(must_get(db.chambers, cid, "StabilityChamber")))


@bp.get("/cosmfg/stability-chambers/<cid>/studies")
@require_roles("QAManager", "PlantDirector")
def list_chamber_studies(cid):
    chamber = must_get(db.chambers, cid, "StabilityChamber")
    items = [s for s in db.studies.values() if s["chamber_id"] == chamber["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_page(items, serialize_study)


@bp.get("/cosmfg/stability-studies/<sid>")
@require_roles("QAManager", "PlantDirector")
def get_study(sid):
    return success(serialize_study(must_get(db.studies, sid, "StabilityStudy")))


@bp.post("/cosmfg/stability-studies/<sid>/readings")
@require_roles("QAManager")
def record_reading(sid):
    study = must_get(db.studies, sid, "StabilityStudy")
    if study["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE", 409,
            "Readings may only be recorded on an IN_PROGRESS study")
    b = body()
    interval = b.get("interval_index")
    if interval is not None and (isinstance(interval, bool)
                                 or not isinstance(interval, int)):
        err("ERR_VALIDATION", 400, "interval_index must be an integer")
    expected = study["required_intervals"][study["recorded_interval_count"]]
    if interval is not None and interval != expected:
        err("ERR_READING_INTERVAL_OUT_OF_ORDER", 422,
            "interval_index does not equal the next required interval")
    if interval is None:
        err("ERR_VALIDATION", 400, "Missing required field: interval_index")
    result = check_enum(get_required(b, "result"), {"PASS", "FAIL"}, "result")
    reading = {
        "id": new_id(),
        "study_id": study["id"],
        "interval_index": interval,
        "result": result,
        "recorded_by_user_id": g.user_id,
        "created_at": iso_now(),
        "_seq": db.next_seq(),
    }
    db.readings[reading["id"]] = reading
    study["recorded_interval_count"] += 1
    completed = False
    if result == "FAIL":
        study["status"] = "COMPLETED_FAIL"
        completed = True
    elif study["recorded_interval_count"] == len(study["required_intervals"]):
        study["status"] = "COMPLETED_PASS"
        completed = True
    touch(study)
    if completed:
        chamber = db.chambers.get(study["chamber_id"])
        if chamber is not None:
            chamber["active_study_count"] = max(0, chamber["active_study_count"] - 1)
            touch(chamber)
    return success(serialize_reading(reading), status=201)


@bp.get("/cosmfg/stability-studies/<sid>/readings")
@require_roles("QAManager", "PlantDirector")
def list_readings(sid):
    study = must_get(db.studies, sid, "StabilityStudy")
    items = [r for r in db.readings.values() if r["study_id"] == study["id"]]
    return list_page(items, serialize_reading)
