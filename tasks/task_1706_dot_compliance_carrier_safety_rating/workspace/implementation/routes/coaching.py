"""CoachingAssignment endpoints (PRD 3.5): OCC-guarded create with supersede,
start/complete/escalate workflow with suspension cascade."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_DRIVER_NOT_ACTIVE, ERR_STALE_VERSION,
    ERR_COACHING_NOT_OPEN, ERR_COACHING_NOT_OVERDUE,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import (
    stamp_new, touch, recompute_driver_risk, maybe_auto_reinstate,
    OPEN_COACHING_STATES,
)
from validate import (
    get_body, req_str, opt_str, req_enum, req_int, req_datetime,
    require_path_resource, require_ref,
)
from util import new_id, CLOCK, fmt_datetime

bp = Blueprint("coaching", __name__)

ROLE = ["SafetyManager"]
COACHING_TYPES = ["VERBAL_WARNING", "TRAINING_COURSE", "PROBATION"]


@bp.post("/safety/coaching-assignments")
def create_assignment():
    caller = authorized(ROLE)
    body = get_body()
    # Stage 3: shape
    driver_id = req_str(body, "driver_id")
    coaching_type = req_enum(body, "coaching_type", COACHING_TYPES)
    due_date = req_datetime(body, "due_date")
    source_violation_id = opt_str(body, "source_violation_id")
    expected_driver_version = req_int(body, "expected_driver_version")
    # Stage 4: body FK existence in declared input order
    driver = require_ref("drivers", driver_id, "driver_id")
    if source_violation_id is not None:
        require_ref("inspection_violations", source_violation_id, "source_violation_id")
    # Stage 5: state
    if driver["employment_status"] != "ACTIVE":
        raise_error(ERR_DRIVER_NOT_ACTIVE, "coaching requires an ACTIVE driver")
    # Stage 6: optimistic concurrency on the driver
    if expected_driver_version != driver["version"]:
        raise_error(ERR_STALE_VERSION, "expected_driver_version is stale")
    # Supersede any open assignment of the same (driver_id, coaching_type)
    for c in db["coaching_assignments"].values():
        if (c["driver_id"] == driver_id and c["coaching_type"] == coaching_type
                and c["status"] in OPEN_COACHING_STATES):
            was_escalated = c["status"] == "ESCALATED"
            c["status"] = "SUPERSEDED"
            touch(c)
            if was_escalated:
                maybe_auto_reinstate(driver)
    assignment = stamp_new({
        "id": new_id(),
        "driver_id": driver_id,
        "coaching_type": coaching_type,
        "source_violation_id": source_violation_id,
        "assigned_by_user_id": caller.user_id,
        "due_date": due_date,
        "completed_at": None,
        "status": "ASSIGNED",
    })
    db["coaching_assignments"][assignment["id"]] = assignment
    touch(driver)
    return success_object(public(assignment), 201)


@bp.get("/safety/coaching-assignments")
def list_assignments():
    return list_response("coaching_assignments", filters={
        "driver_id": request.args.get("driver_id"),
        "status": request.args.get("status"),
        "source_violation_id": request.args.get("source_violation_id"),
    })


@bp.get("/safety/coaching-assignments/<rid>")
def get_assignment(rid):
    return get_one("coaching_assignments", rid)


@bp.post("/safety/coaching-assignments/<rid>/start")
def start(rid):
    authorized(ROLE)
    assignment = require_path_resource("coaching_assignments", rid)
    if assignment["status"] != "ASSIGNED":
        raise_error(ERR_COACHING_NOT_OPEN, "start requires ASSIGNED")
    assignment["status"] = "IN_PROGRESS"
    touch(assignment)
    return success_object(public(assignment))


@bp.post("/safety/coaching-assignments/<rid>/complete")
def complete(rid):
    authorized(ROLE)
    body = get_body()
    req_str(body, "completion_note")
    assignment = require_path_resource("coaching_assignments", rid)
    if assignment["status"] not in OPEN_COACHING_STATES:
        raise_error(ERR_COACHING_NOT_OPEN, "complete requires an open assignment")
    was_escalated = assignment["status"] == "ESCALATED"
    assignment["status"] = "COMPLETED"
    assignment["completed_at"] = fmt_datetime(CLOCK.now())
    touch(assignment)
    driver = db["drivers"].get(assignment["driver_id"])
    if driver is not None:
        recompute_driver_risk(driver)
        if was_escalated:
            maybe_auto_reinstate(driver)
    return success_object(public(assignment))


@bp.post("/safety/coaching-assignments/<rid>/escalate")
def escalate(rid):
    authorized(ROLE)
    assignment = require_path_resource("coaching_assignments", rid)
    if assignment["status"] != "OVERDUE":
        raise_error(ERR_COACHING_NOT_OVERDUE, "escalate requires OVERDUE")
    driver = db["drivers"].get(assignment["driver_id"])
    if driver is None or driver["employment_status"] != "ACTIVE":
        raise_error(ERR_DRIVER_NOT_ACTIVE, "escalate requires an ACTIVE driver")
    assignment["status"] = "ESCALATED"
    touch(assignment)
    driver["employment_status"] = "SUSPENDED"
    driver["coaching_strikes"] += 1
    touch(driver)
    return success_object(public(assignment))
