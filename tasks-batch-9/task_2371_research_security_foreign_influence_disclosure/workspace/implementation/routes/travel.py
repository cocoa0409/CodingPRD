"""Foreign travel registration and device security (PRD 3.7)."""

from flask import Blueprint

import db
import response
import util
import validate
from errors import ApiError
from middleware import INVESTIGATOR, RSO, require, require_any
from routes.common import must_exist, render_list
from services import cascade, derive, enums as E, present

bp = Blueprint("travel", __name__)

TRAVEL_TRANSITIONS = {
    ("DRAFT", "SUBMITTED"): (INVESTIGATOR,),
    ("DRAFT", "CANCELLED"): (INVESTIGATOR,),
    ("SUBMITTED", "APPROVED"): (RSO,),
    ("SUBMITTED", "DENIED"): (RSO,),
    ("SUBMITTED", "CANCELLED"): (INVESTIGATOR,),
    ("APPROVED", "CANCELLED"): (INVESTIGATOR, RSO),
    ("APPROVED", "COMPLETED"): (RSO,),
}


@bp.post("/travel-registrations")
def create_registration():
    user_id, role = require(INVESTIGATOR, RSO)
    data = validate.body()

    raw_investigator = data.get("investigator_id")
    if role == INVESTIGATOR and isinstance(raw_investigator, str) and \
            raw_investigator != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The acting investigator does not own this registration.")

    investigator = must_exist("investigator", raw_investigator)
    project = None
    if data.get("project_id") is not None:
        project = must_exist("project", data.get("project_id"))
    host = None
    if data.get("host_organization_id") is not None:
        host = must_exist("organization", data.get("host_organization_id"))

    country = validate.req_country_code(data, "destination_country_code")
    depart_on = validate.req_instant(data, "depart_on")
    return_on = validate.req_instant(data, "return_on")
    purpose = validate.req_enum(data, "purpose", E.TRAVEL_PURPOSES)
    carries = validate.opt_bool(data, "carries_institutional_device", default=True)

    if util.parse_dt(return_on) < util.parse_dt(depart_on):
        raise ApiError("ERR_INVALID_TRAVEL_WINDOW",
                       "return_on must be on or after depart_on.")

    record = db.base_record()
    record.update({
        "investigator_id": investigator["id"],
        "project_id": project["id"] if project else None,
        "host_organization_id": host["id"] if host else None,
        "destination_country_code": country,
        "depart_on": depart_on,
        "return_on": return_on,
        "purpose": purpose,
        "carries_institutional_device": carries,
        "risk_flag_count": 0,
        "device_requirement_tier": "STANDARD",
        "briefing_required": False,
        "status": "DRAFT",
        "device_decision_recorded_at": None,
    })
    derive.compute_travel_device(record)
    db.travel[record["id"]] = record
    return response.object_response(present.travel(record), 201)


@bp.get("/travel-registrations/<registration_id>")
def read_registration(registration_id):
    require_any()
    record = must_exist("travel", registration_id)
    return response.object_response(present.travel(record))


@bp.get("/travel-registrations")
def list_registrations():
    require_any()
    investigator_id = validate.filter_value("investigator_id")
    project_id = validate.filter_value("project_id")
    host_id = validate.filter_value("host_organization_id")
    status = validate.filter_enum("status", E.TRAVEL_STATUSES)

    rows = []
    for record in db.ordered(db.travel.values()):
        if investigator_id and record["investigator_id"] != investigator_id:
            continue
        if project_id and record["project_id"] != project_id:
            continue
        if host_id and record["host_organization_id"] != host_id:
            continue
        if status and record["status"] != status:
            continue
        rows.append(record)
    return render_list(rows, present.travel)


@bp.post("/travel-registrations/<registration_id>/status")
def set_registration_status(registration_id):
    user_id, role = require(INVESTIGATOR, RSO)
    data = validate.body()
    record = must_exist("travel", registration_id)

    # step 3 — ownership for Investigator-role callers
    if role == INVESTIGATOR and record["investigator_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The acting investigator does not own this registration.")

    to_status = validate.req_enum(data, "to_status", E.TRAVEL_STATUSES)
    current = record["status"]
    key = (current, to_status)
    if key not in TRAVEL_TRANSITIONS:
        raise ApiError("ERR_INVALID_TRAVEL_TRANSITION",
                       "Travel status cannot move %s -> %s." % (current, to_status))
    if role not in TRAVEL_TRANSITIONS[key]:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s may not move a registration %s -> %s."
                       % (role, current, to_status))

    investigator = db.investigators.get(record["investigator_id"])
    now = db.clock_dt()

    if to_status == "SUBMITTED":
        if util.parse_dt(record["depart_on"]) >= util.parse_dt(record["return_on"]):
            raise ApiError("ERR_INVALID_TRAVEL_WINDOW",
                           "depart_on must fall strictly before return_on.")
        if derive.travel_conflicts(record):
            raise ApiError("ERR_TRAVEL_WINDOW_CONFLICT",
                           "The trip collides with another live registration.")
        record["status"] = "SUBMITTED"
        derive.compute_travel_device(record)
        db.touch(record)

    elif to_status == "APPROVED":
        if investigator is not None and \
                derive.posture_of(investigator) == "SUSPENDED":
            raise ApiError("ERR_INVESTIGATOR_SUSPENDED",
                           "A SUSPENDED investigator cannot travel.")
        tier = record["device_requirement_tier"]
        if tier in ("LOANER_REQUIRED", "LOANER_PLUS_ESCORT"):
            if not derive.has_satisfied_course(record["investigator_id"],
                                               "FOREIGN_TRAVEL_BRIEF"):
                raise ApiError("ERR_TRAVEL_BRIEFING_REQUIRED",
                               "A FOREIGN_TRAVEL_BRIEF assignment must be "
                               "COMPLETED or WAIVED.")
        if tier == "LOANER_PLUS_ESCORT":
            acknowledged = any(
                d["plan_status"] == "PLAN_ACKNOWLEDGED"
                for d in derive.investigator_disclosures(record["investigator_id"]))
            if not acknowledged:
                raise ApiError("ERR_MANAGEMENT_PLAN_REQUIRED",
                               "An acknowledged management plan is required.")
        record["status"] = "APPROVED"
        record["device_decision_recorded_at"] = db.clock_str()
        db.touch(record)

    elif to_status == "CANCELLED":
        if current == "APPROVED":
            if now >= util.parse_dt(record["depart_on"]):
                raise ApiError("ERR_TRAVEL_ALREADY_STARTED",
                               "The trip has already departed.")
        record["status"] = "CANCELLED"
        db.touch(record)

    elif to_status == "COMPLETED":
        if now < util.parse_dt(record["return_on"]):
            raise ApiError("ERR_TRAVEL_NOT_ENDED",
                           "The trip has not returned yet.")
        record["status"] = "COMPLETED"
        db.touch(record)

    else:  # DENIED
        record["status"] = "DENIED"
        db.touch(record)

    return response.object_response(present.travel(record))
