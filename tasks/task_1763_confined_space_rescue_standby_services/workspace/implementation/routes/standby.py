"""Standby rescue-team staffing (PRD section 3.5)."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    ERR_ASSIGNMENT_INVALID_STATE, ERR_ASSIGNMENT_NOT_FOUND,
    ERR_CHECKIN_WINDOW_EXPIRED, ERR_CHECKIN_WINDOW_NOT_OPEN,
    ERR_INVALID_TIME_RANGE, ERR_PERMIT_INVALID_STATE,
    ERR_PERSONNEL_NOT_FOUND, ERR_PERSONNEL_NOT_QUALIFIED,
    ERR_RESCUE_PLAN_NOT_APPROVED, ERR_STANDBY_OVERLAP, raise_error,
)
from helpers import (
    body, iso_z, list_response, now_dt, parse_dt, reject_unknown, req_datetime,
    req_string, stamp_new, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from routes.permits import get_permit
from services import (
    STANDBY_CHECKIN_EARLY, approved_plan_for_space, cancel_scheduled_assignment,
    permit_of, recompute_committed, release_assignment, space_of_permit,
)

bp = Blueprint("standby", __name__)


def get_assignment(assignment_id):
    a = db.standby_assignments.get(assignment_id)
    if a is None:
        raise_error(ERR_ASSIGNMENT_NOT_FOUND, "Standby assignment not found")
    return a


@bp.route("/rescue-ops/entry-permits/<permit_id>/standby-assignments", methods=["POST"])
def create_assignment(permit_id):
    require_auth(("RescueTeamLead",))
    permit = get_permit(permit_id)
    data = body()
    reject_unknown(data, {"rescuer_id", "standby_start_at", "standby_end_at"})
    rescuer_id = req_string(data, "rescuer_id")
    rescuer = db.personnel.get(rescuer_id)
    if rescuer is None:
        raise_error(ERR_PERSONNEL_NOT_FOUND, "Rescuer not found")
    standby_start = req_datetime(data, "standby_start_at")
    standby_end = req_datetime(data, "standby_end_at")
    if not standby_end > standby_start:
        raise_error(ERR_INVALID_TIME_RANGE,
                    "standby_end_at must be strictly after standby_start_at")
    # State gate (priority 7)
    if permit["status"] not in ("ISSUED", "ACTIVE", "SUSPENDED"):
        raise_error(ERR_PERMIT_INVALID_STATE,
                    "Standby may be scheduled only while the permit is ISSUED, ACTIVE, or SUSPENDED")
    # Temporal gate (priority 12): half-open overlap per rescuer; touching
    # windows are legal and no rest buffer applies to standby.
    for other in db.standby_assignments.values():
        if other["rescuer_id"] != rescuer_id \
                or other["status"] not in ("SCHEDULED", "ON_STANDBY", "DEPLOYED"):
            continue
        existing_start = parse_dt(other["standby_start_at"])
        existing_end = parse_dt(other["standby_end_at"])
        if standby_start < existing_end and existing_start < standby_end:
            raise_error(ERR_STANDBY_OVERLAP,
                        "Standby window overlaps another assignment of this rescuer")
    # Referential gates (priority 13): approved plan, rescuer qualification
    space = space_of_permit(permit)
    plan = approved_plan_for_space(space["id"]) if space else None
    if plan is None:
        raise_error(ERR_RESCUE_PLAN_NOT_APPROVED, "No APPROVED rescue plan exists for the space")
    if rescuer["status"] != "ACTIVE" or "RESCUER" not in rescuer["role_qualifications"]:
        raise_error(ERR_PERSONNEL_NOT_QUALIFIED,
                    "Standby rescuers must be ACTIVE and hold the RESCUER qualification")
    missing = [c for c in plan["required_certifications"] if c not in rescuer["certifications"]]
    if missing:
        raise_error(ERR_PERSONNEL_NOT_QUALIFIED,
                    "Rescuer lacks certifications required by the approved plan")
    assignment = {
        "permit_id": permit["id"],
        "rescuer_id": rescuer_id,
        "standby_start_at": iso_z(standby_start),
        "standby_end_at": iso_z(standby_end),
        "checked_in_at": None,
        "checked_out_at": None,
        "deployed_at": None,
        "billable_minutes": None,
        "line_amount_cents": None,
        "billed": False,
        "status": "SCHEDULED",
    }
    stamp_new(assignment)
    db.standby_assignments[assignment["id"]] = assignment
    recompute_committed(rescuer_id)
    return success_object(serializers.standby_assignment(assignment), 201)


@bp.route("/rescue-ops/standby-assignments", methods=["GET"])
def list_assignments():
    require_auth(ALL_ROLES)
    return list_response(list(db.standby_assignments.values()),
                         serializers.standby_assignment, {
                             "permit_id": request.args.get("permit_id"),
                             "rescuer_id": request.args.get("rescuer_id"),
                             "status": request.args.get("status"),
                         })


@bp.route("/rescue-ops/standby-assignments/<assignment_id>", methods=["GET"])
def get_one_assignment(assignment_id):
    require_auth(ALL_ROLES)
    return success_object(serializers.standby_assignment(get_assignment(assignment_id)))


@bp.route("/rescue-ops/standby-assignments/<assignment_id>/check-in", methods=["POST"])
def check_in_assignment(assignment_id):
    require_auth(("RescueTeamLead",))
    assignment = get_assignment(assignment_id)
    body()
    if assignment["status"] != "SCHEDULED":
        raise_error(ERR_ASSIGNMENT_INVALID_STATE, "Only a SCHEDULED assignment can be checked in")
    permit = permit_of(assignment)
    if permit is None or permit["status"] not in ("ISSUED", "ACTIVE", "SUSPENDED"):
        raise_error(ERR_PERMIT_INVALID_STATE,
                    "Parent permit must be ISSUED, ACTIVE, or SUSPENDED for standby check-in")
    now = now_dt()
    if now < parse_dt(assignment["standby_start_at"]) - STANDBY_CHECKIN_EARLY:
        raise_error(ERR_CHECKIN_WINDOW_NOT_OPEN, "Standby check-in window is not yet open")
    if now > parse_dt(assignment["standby_end_at"]):
        raise_error(ERR_CHECKIN_WINDOW_EXPIRED, "Standby check-in window has expired")
    assignment["status"] = "ON_STANDBY"
    assignment["checked_in_at"] = iso_z(now)
    touch(assignment)
    return success_object(serializers.standby_assignment(assignment))


@bp.route("/rescue-ops/standby-assignments/<assignment_id>/release", methods=["POST"])
def release_assignment_endpoint(assignment_id):
    require_auth(("RescueTeamLead",))
    assignment = get_assignment(assignment_id)
    body()
    if assignment["status"] not in ("ON_STANDBY", "DEPLOYED"):
        raise_error(ERR_ASSIGNMENT_INVALID_STATE,
                    "Only an ON_STANDBY or DEPLOYED assignment can be released")
    release_assignment(assignment, now_dt())
    return success_object(serializers.standby_assignment(assignment))


@bp.route("/rescue-ops/standby-assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_assignment(assignment_id):
    require_auth(("RescueTeamLead",))
    assignment = get_assignment(assignment_id)
    body()
    if assignment["status"] != "SCHEDULED":
        raise_error(ERR_ASSIGNMENT_INVALID_STATE, "Only a SCHEDULED assignment can be cancelled")
    cancel_scheduled_assignment(assignment)
    return success_object(serializers.standby_assignment(assignment))
