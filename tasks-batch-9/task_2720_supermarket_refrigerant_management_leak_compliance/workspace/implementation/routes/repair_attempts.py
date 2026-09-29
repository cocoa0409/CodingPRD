"""Repair attempts (PRD 3.5)."""
from flask import Blueprint, request

import constants
import db
import response
import util
import validate
from errors import ApiError
from middleware import TECHNICIAN, endpoint, read_endpoint, require_technician_identity
from services import deadlines, guards, posture

bp = Blueprint("repair_attempts", __name__)

ACCEPTING_STATUSES = ("OPEN", "REPAIR_OVERDUE", "VERIFICATION_FAILED",
                      "VERIFICATION_PENDING")


@bp.post("/repair-attempts")
@endpoint([TECHNICIAN])
def create_repair_attempt():
    payload = validate.body()
    leak_event_id = validate.req_id(payload, "leak_event_id")
    system_id = validate.req_id(payload, "system_id")
    technician_id = validate.req_id(payload, "technician_id")
    recovery_equipment_id = validate.req_id(payload, "recovery_equipment_id")
    repair_method_code = validate.req_enum(payload, "repair_method_code",
                                           constants.REPAIR_METHOD_CODES)
    repair_completed_at = validate.req_instant(payload, "repair_completed_at")

    db.require("systems", system_id)
    technician = db.require("technicians", technician_id)
    equipment = db.require("recovery_equipment", recovery_equipment_id)
    event = db.require("leak_events", leak_event_id)

    require_technician_identity(technician_id)
    guards.require_event_not_terminal(event)
    guards.require_state(event["status"] in ACCEPTING_STATUSES)
    if event["status"] == "VERIFICATION_FAILED":
        guards.require_state(
            event["failed_verification_count"] < constants.MAX_FAILED_VERIFICATIONS)

    system = db.require("systems", event["system_id"])
    guards.require_not_suspended(technician)
    guards.require_certification_current(technician, repair_completed_at)
    guards.require_certification_class(technician, system)
    guards.require_equipment_certified(equipment)
    guards.require_same_store(equipment, system["store_id"])
    if system_id != event["system_id"]:
        raise ApiError("ERR_LEAK_EVENT_SYSTEM_MISMATCH")
    guards.require_not_after_clock(repair_completed_at)
    if repair_completed_at < event["detected_at"]:
        raise ApiError("ERR_REPAIR_BEFORE_DETECTION")
    guards.require_instant_free_for_technician(technician_id, repair_completed_at)

    from_status = event["status"]
    if from_status == "VERIFICATION_PENDING":
        # A re-repair supersedes every attempt still awaiting verification.
        for existing in deadlines.event_attempts(event["id"]):
            if existing["outcome"] == "AWAITING_VERIFICATION":
                existing["outcome"] = "SUPERSEDED"

    was_late = deadlines.is_overdue(event["repair_deadline"], repair_completed_at)
    if from_status == "REPAIR_OVERDUE":
        was_late = True

    attempt = db.new_entity(versioned=False)
    attempt.update({
        "leak_event_id": event["id"],
        "technician_id": technician_id,
        "recovery_equipment_id": recovery_equipment_id,
        "repair_method_code": repair_method_code,
        "repair_completed_at": repair_completed_at,
        "attempt_number": 1,
        "outcome": "AWAITING_VERIFICATION",
        "was_late": was_late,
    })
    db.insert("repair_attempts", attempt)
    ordered = deadlines.event_attempts(event["id"])
    attempt["attempt_number"] = ordered.index(attempt) + 1

    event_snap = db.snapshot(event)
    event["repair_attempt_count"] = event["repair_attempt_count"] + 1
    event["last_repair_completed_at"] = repair_completed_at
    event["verification_deadline"] = util.add_days(
        repair_completed_at, constants.VERIFICATION_WINDOW_DAYS)
    if was_late:
        event["late_repair_flag"] = True
    event["status"] = "VERIFICATION_PENDING"
    db.commit(event, event_snap)

    technician_snap = db.snapshot(technician)
    technician["repair_attempt_count"] = technician["repair_attempt_count"] + 1
    db.commit(technician, technician_snap)

    posture.recompute_store_by_id(system["store_id"])
    return response.created(attempt)


@bp.get("/repair-attempts")
@read_endpoint
def list_repair_attempts():
    filters = {
        "leak_event_id": request.args.get("leak_event_id"),
        "technician_id": request.args.get("technician_id"),
        "recovery_equipment_id": request.args.get("recovery_equipment_id"),
        "outcome": request.args.get("outcome"),
    }
    return response.listing(db.values("repair_attempts"), filters)


@bp.get("/repair-attempts/<attempt_id>")
@read_endpoint
def get_repair_attempt(attempt_id):
    return response.ok(db.require("repair_attempts", attempt_id))
