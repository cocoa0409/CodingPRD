"""Inspection endpoints: scheduling (closed buffered intervals, PRD 2.11),
outcome recording with OCC, and certificate posting."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import resolve
import store
from auth import authenticate, authorize
from errors import (
    raise_err,
    ERR_INSPECTION_SCHEDULE_CONFLICT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
)
from services import (
    ANNUAL_KINDS,
    INSPECTION_BUFFER_HOURS,
    INSPECTION_DURATION_HOURS,
    INSPECTION_KINDS,
    OUTCOMES,
    apply_outcome,
    inspection_json,
    inspections_of,
)
from util import (
    body_json,
    list_response,
    new_record,
    opt_dt,
    opt_num,
    opt_str,
    req_enum,
    req_dt,
    req_str,
    success_object,
    touch,
)

bp = Blueprint("inspections", __name__)

SCHEDULERS = ["PlantManager", "Inspector"]
READERS = ["PlantManager", "Operator", "Inspector"]


def _buffered_window(scheduled_on):
    """Closed occupancy: [t - buffer, t + duration + buffer] (PRD 2.11)."""
    start = scheduled_on - timedelta(hours=INSPECTION_BUFFER_HOURS)
    end = scheduled_on + timedelta(hours=INSPECTION_DURATION_HOURS + INSPECTION_BUFFER_HOURS)
    return start, end


@bp.post("/plants/<plantId>/boilers/<boilerId>/inspections")
def create_inspection(plantId, boilerId):
    _, role = authenticate()
    authorize(role, SCHEDULERS)
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    body = body_json()
    kind = req_enum(body, "inspection_kind", INSPECTION_KINDS)
    scheduled_on = req_dt(body, "scheduled_on")
    inspector_name = req_str(body, "inspector_name")
    inspector_license_no = req_str(body, "inspector_license_no")
    lift = opt_num(body, "relief_valve_lift_pressure_psi", None)
    # schedule conflict(13): closed buffered intervals; touching DOES conflict
    ns, ne = _buffered_window(scheduled_on)
    for other in inspections_of(boiler["id"]):
        if other["outcome"] != "PENDING":
            continue
        os_, oe = _buffered_window(other["scheduled_on"])
        if ns <= oe and os_ <= ne:
            raise_err(ERR_INSPECTION_SCHEDULE_CONFLICT,
                      "Another PENDING inspection occupies an overlapping buffered interval")
    rec = new_record()
    rec.update({
        "boiler_id": boiler["id"],
        "inspection_kind": kind,
        "scheduled_on": scheduled_on,
        "inspector_name": inspector_name,
        "inspector_license_no": inspector_license_no,
        "relief_valve_lift_pressure_psi": lift,
        "outcome": "PENDING",
        "certificate_number": None,
        "certificate_expires_on": None,
        "posted_at": None,
        "_outcome_event": None,
    })
    store.inspections[rec["id"]] = rec
    return success_object(inspection_json(rec), 201)


@bp.get("/plants/<plantId>/boilers/<boilerId>/inspections/<inspectionId>")
def get_inspection(plantId, boilerId, inspectionId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    rec = resolve.inspection(boiler, inspectionId)
    return success_object(inspection_json(rec))


@bp.get("/plants/<plantId>/boilers/<boilerId>/inspections")
def list_inspections(plantId, boilerId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    recs = inspections_of(boiler["id"])
    outcome = request.args.get("outcome")
    if outcome is not None:
        recs = [i for i in recs if i["outcome"] == outcome]
    return list_response(recs, inspection_json)


@bp.post("/plants/<plantId>/boilers/<boilerId>/inspections/<inspectionId>/record-outcome")
def record_outcome(plantId, boilerId, inspectionId):
    _, role = authenticate()
    authorize(role, SCHEDULERS)
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    insp = resolve.inspection(boiler, inspectionId)
    body = body_json()
    outcome = req_enum(body, "outcome", OUTCOMES)
    certificate_number = opt_str(body, "certificate_number")
    certificate_expires_on = opt_dt(body, "certificate_expires_on")
    lift = opt_num(body, "relief_valve_lift_pressure_psi", None)
    expected = body.get("expected_inspection_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST,
                  "expected_inspection_version is required and must be an integer")
    if outcome == "PASSED" and insp["inspection_kind"] in ANNUAL_KINDS and not certificate_number:
        raise_err(ERR_INVALID_REQUEST,
                  "certificate_number is required when recording PASSED for an annual inspection")
    if outcome == "PASSED" and insp["inspection_kind"] == "RELIEF_VALVE_POP" and lift is None:
        lift = insp["relief_valve_lift_pressure_psi"]
    if outcome == "PASSED" and insp["inspection_kind"] == "RELIEF_VALVE_POP" and lift is None:
        raise_err(ERR_INVALID_REQUEST,
                  "relief_valve_lift_pressure_psi is required to pass a RELIEF_VALVE_POP test")
    # state(4): PENDING only
    if insp["outcome"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Inspection outcome has already been recorded")
    # OCC(22): stale expected_inspection_version rejected
    if expected != insp["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_inspection_version does not match the inspection's current version")
    apply_outcome(plant, boiler, insp, outcome, certificate_number,
                  certificate_expires_on, lift)
    return success_object(inspection_json(insp))


@bp.post("/plants/<plantId>/boilers/<boilerId>/inspections/<inspectionId>/post")
def post_certificate(plantId, boilerId, inspectionId):
    _, role = authenticate()
    authorize(role, ["PlantManager"])
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    insp = resolve.inspection(boiler, inspectionId)
    # state(4): only a PASSED inspection yields a postable certificate
    if insp["outcome"] != "PASSED":
        raise_err(ERR_INVALID_STATE, "Only a PASSED inspection certificate can be posted")
    insp["posted_at"] = clock.now()
    touch(insp)
    return success_object(inspection_json(insp))
