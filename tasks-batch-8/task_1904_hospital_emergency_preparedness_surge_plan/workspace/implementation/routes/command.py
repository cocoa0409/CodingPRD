"""Command role assignments (OCC-guarded)."""

from flask import Blueprint, request

from db import clock, store
from domain import COMMAND_ROLES, get_or_404, list_response, ser_assignment
from envelope import success
from errors import ApiError
from security import ALL_ROLES, authorize
from util import field_enum, field_int, field_str, new_entity, require_body, touch

bp = Blueprint("command", __name__)


@bp.post("/command-assignments")
@authorize(["IncidentCommander"])
def create_assignment():
    body = require_body()
    incident_id = field_str(body, "incident_id", required=True)
    staff_member_id = field_str(body, "staff_member_id", required=True)
    command_role = field_enum(body, "command_role", COMMAND_ROLES, required=True)
    expected_version = field_int(body, "expected_incident_version", required=True)

    incident = get_or_404("incidents", incident_id)
    staff = get_or_404("staff_members", staff_member_id)

    # Optimistic concurrency control (priority 7).
    if expected_version != incident["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_incident_version does not match the incident's version")

    # Incident posture gate (priority 9).
    if incident["status"] != "ACTIVATED":
        raise ApiError("ERR_INCIDENT_NOT_ACTIVATED", 409,
                       "command assignments require an ACTIVATED incident")

    if command_role not in staff["role_qualifications"]:
        raise ApiError("ERR_STAFF_NOT_QUALIFIED", 422,
                       "staff member is not qualified for command role %s" % command_role)

    # Relieve-and-reassign: any existing ACTIVE holder of this role is relieved.
    for other in store["command_assignments"].values():
        if (other["incident_id"] == incident_id
                and other["command_role"] == command_role
                and other["status"] == "ACTIVE"):
            other["status"] = "RELIEVED"
            touch(other)

    assignment = new_entity()
    assignment.update({
        "incident_id": incident_id,
        "staff_member_id": staff_member_id,
        "command_role": command_role,
        "status": "ACTIVE",
        "assigned_at": clock.now(),
    })
    store["command_assignments"][assignment["id"]] = assignment

    # The write advances the incident's version, invalidating stale views.
    touch(incident)
    return success(ser_assignment(assignment), "object", 201)


@bp.get("/command-assignments")
@authorize(ALL_ROLES)
def list_assignments():
    incident_id = request.args.get("incident_id")
    staff_member_id = request.args.get("staff_member_id")
    status = request.args.get("status")

    def predicate(a):
        if incident_id is not None and a["incident_id"] != incident_id:
            return False
        if staff_member_id is not None and a["staff_member_id"] != staff_member_id:
            return False
        if status is not None and a["status"] != status:
            return False
        return True

    return list_response("command_assignments", ser_assignment, predicate)


@bp.get("/command-assignments/<assignment_id>")
@authorize(ALL_ROLES)
def get_assignment(assignment_id):
    return success(ser_assignment(get_or_404("command_assignments", assignment_id)),
                   "object", 200)
