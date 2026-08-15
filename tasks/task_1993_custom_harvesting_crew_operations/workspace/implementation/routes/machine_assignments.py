"""MachineAssignment endpoints (§3.4)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_MACHINE_OVERLAP,
    ERR_ASSIGNMENT_NOT_RESERVED,
)
from helpers import (
    get_json_body,
    require_fields,
    require_type,
    parse_date,
    stamp_new,
    touch,
    public,
    sort_key,
    get_stop_or_404,
    get_machine_or_404,
    get_assignment_or_404,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination, paginate
from services.domain import (
    machine_has_active_assignment,
    release_machine_if_unallocated,
)

bp = Blueprint("machine_assignments", __name__)


@bp.route("/harvest/machine-assignments", methods=["POST"])
def create_assignment():
    require_roles("CrewBoss")
    body = get_json_body()
    require_fields(
        body,
        ["route_stop_id", "machine_id", "assigned_start_date", "assigned_end_date"],
    )
    route_stop_id = require_type(body, "route_stop_id", "string")
    machine_id = require_type(body, "machine_id", "string")
    new_start = parse_date(body["assigned_start_date"], "assigned_start_date")
    new_end = parse_date(body["assigned_end_date"], "assigned_end_date")
    if new_end <= new_start:
        from errors import ERR_INVALID_REQUEST
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "assigned_end_date must be after assigned_start_date (half-open interval)",
        )

    # Existence, left-to-right: route stop, then machine.
    stop = get_stop_or_404(route_stop_id)
    machine = get_machine_or_404(machine_id)

    # Half-open overlap rule (priority 7): reject if any existing
    # RESERVED/DEPLOYED assignment for the same machine has
    # existing.start < new.end AND new.start < existing.end.
    # Pure adjacency is allowed.
    for existing in db.machine_assignments.values():
        if existing["machine_id"] != machine["id"]:
            continue
        if existing["status"] not in ("RESERVED", "DEPLOYED"):
            continue
        ex_start = parse_date(existing["assigned_start_date"], "assigned_start_date")
        ex_end = parse_date(existing["assigned_end_date"], "assigned_end_date")
        if ex_start < new_end and new_start < ex_end:
            raise ApiError(
                ERR_MACHINE_OVERLAP,
                409,
                "Half-open interval overlap with another RESERVED/DEPLOYED assignment on the same machine",
            )

    record = stamp_new(
        {
            "route_stop_id": stop["id"],
            "machine_id": machine["id"],
            "assigned_start_date": body["assigned_start_date"],
            "assigned_end_date": body["assigned_end_date"],
            "status": "RESERVED",
        }
    )
    db.machine_assignments[record["id"]] = record
    # Machine AVAILABLE → ASSIGNED when the first active reservation lands.
    if machine["status"] == "AVAILABLE":
        machine["status"] = "ASSIGNED"
        touch(machine)
    return success_object(public(record), status=201)


@bp.route("/harvest/machine-assignments", methods=["GET"])
def list_assignments():
    require_roles(*ALL_ROLES)
    pagination = parse_pagination(request.args)
    route_stop_id = request.args.get("route_stop_id")
    machine_id = request.args.get("machine_id")
    items = list(db.machine_assignments.values())
    if route_stop_id is not None:
        items = [a for a in items if a["route_stop_id"] == route_stop_id]
    if machine_id is not None:
        items = [a for a in items if a["machine_id"] == machine_id]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/machine-assignments/<assignmentId>", methods=["GET"])
def get_assignment(assignmentId):
    require_roles(*ALL_ROLES)
    assignment = get_assignment_or_404(assignmentId)
    return success_object(public(assignment))


@bp.route("/harvest/machine-assignments/<assignmentId>/cancel", methods=["POST"])
def cancel_assignment(assignmentId):
    require_roles("CrewBoss")
    assignment = get_assignment_or_404(assignmentId)
    if assignment["status"] != "RESERVED":
        raise ApiError(
            ERR_ASSIGNMENT_NOT_RESERVED, 409, "cancel requires assignment RESERVED"
        )
    assignment["status"] = "CANCELLED"
    touch(assignment)
    # If this was the machine's last non-CANCELLED assignment and the
    # machine was ASSIGNED, the machine returns to AVAILABLE.
    release_machine_if_unallocated(
        assignment["machine_id"], exclude_assignment_id=assignment["id"]
    )
    return success_object(public(assignment))
