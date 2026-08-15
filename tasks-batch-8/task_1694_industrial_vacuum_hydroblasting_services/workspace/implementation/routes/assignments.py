"""Assignments: crew and equipment windows (PRD 3.2)."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (ERR_INVALID_WINDOW, ERR_OPERATOR_NOT_CERTIFIED,
                    ERR_OPERATOR_REST_PERIOD, ERR_RESOURCE_SCHEDULE_CONFLICT,
                    bad_request, conflict, invalid_state, not_found,
                    unprocessable)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from util import (get_body, list_paginated, new_entity, req_field, rhu, touch)

bp = Blueprint("assignments", __name__)

RESOURCE_KINDS = ["EQUIPMENT", "OPERATOR"]
ASSIGNMENT_STATUSES = ["SCHEDULED", "CONFIRMED", "RELEASED", "CANCELLED"]
REST_BUFFER = timedelta(hours=10)


def _get_assignment(assignment_id):
    assignment = store.assignments.get(assignment_id)
    if assignment is None:
        raise not_found("Assignment not found")
    return assignment


@bp.post("/v1/assignments")
def create_assignment():
    require_roles(["ProjectManager"])
    body = get_body()
    job_id = req_field(body, "job_id")
    resource_kind = req_field(body, "resource_kind", choices=RESOURCE_KINDS)
    # Exactly the one FK matching resource_kind; the other is forbidden.
    equipment_unit_id = body.get("equipment_unit_id")
    operator_id = body.get("operator_id")
    if resource_kind == "EQUIPMENT":
        if equipment_unit_id is None:
            raise bad_request("equipment_unit_id is required when resource_kind is EQUIPMENT")
        if operator_id is not None:
            raise bad_request("operator_id is forbidden when resource_kind is EQUIPMENT")
        if not isinstance(equipment_unit_id, str):
            raise bad_request("equipment_unit_id must be a string")
    else:
        if operator_id is None:
            raise bad_request("operator_id is required when resource_kind is OPERATOR")
        if equipment_unit_id is not None:
            raise bad_request("equipment_unit_id is forbidden when resource_kind is OPERATOR")
        if not isinstance(operator_id, str):
            raise bad_request("operator_id must be a string")
    window_start = req_field(body, "window_start", kind="datetime")
    window_end = req_field(body, "window_end", kind="datetime")

    # Existence, left to right: job first, then the resource FK.
    job = store.jobs.get(job_id)
    if job is None:
        raise not_found("Job not found")
    unit = None
    operator = None
    if resource_kind == "EQUIPMENT":
        unit = store.equipment_units.get(equipment_unit_id)
        if unit is None:
            raise not_found("Equipment unit not found")
    else:
        operator = store.operators.get(operator_id)
        if operator is None:
            raise not_found("Operator not found")

    if job["execution_status"] not in ("QUOTED", "SCHEDULED", "MOBILIZED"):
        raise invalid_state(
            "Assignments can only be added while the job is QUOTED, SCHEDULED or MOBILIZED")

    # Operator certification: HAZWOPER expiry must cover the full window.
    if operator is not None:
        from util import parse_date
        expiry = parse_date(operator["hazwoper_expires_on"])
        if expiry is None or expiry < window_end.date():
            raise unprocessable(
                ERR_OPERATOR_NOT_CERTIFIED,
                "Operator HAZWOPER certification does not cover the assignment window")

    if not window_end > window_start:
        raise unprocessable(ERR_INVALID_WINDOW,
                            "window_end must be later than window_start")

    live = [a for a in store.assignments.values()
            if a["status"] in ("SCHEDULED", "CONFIRMED")]
    if resource_kind == "EQUIPMENT":
        # Half-open overlap: adjacency (end == start) is allowed.
        for other in live:
            if other["resource_kind"] != "EQUIPMENT":
                continue
            if other["equipment_unit_id"] != equipment_unit_id:
                continue
            if not (window_end <= other["window_start"]
                    or window_start >= other["window_end"]):
                raise conflict(ERR_RESOURCE_SCHEDULE_CONFLICT,
                               "Equipment unit has an overlapping assignment")
    else:
        # Ten-hour rest buffer around every other live assignment.
        for other in live:
            if other["resource_kind"] != "OPERATOR":
                continue
            if other["operator_id"] != operator_id:
                continue
            if not (window_end + REST_BUFFER <= other["window_start"]
                    or window_start >= other["window_end"] + REST_BUFFER):
                raise conflict(ERR_OPERATOR_REST_PERIOD,
                               "Operator has an assignment within the ten-hour rest buffer")

    hours = rhu((window_end - window_start).total_seconds() / 3600, 2)
    assignment = new_entity(store.assignments, {
        "job_id": job_id,
        "resource_kind": resource_kind,
        "equipment_unit_id": equipment_unit_id if resource_kind == "EQUIPMENT" else None,
        "operator_id": operator_id if resource_kind == "OPERATOR" else None,
        "window_start": window_start,
        "window_end": window_end,
        "window_hours": hours,
        "status": "SCHEDULED",
    })
    return success_object(assignment, status=201)


@bp.get("/v1/assignments")
def list_assignments():
    require_roles(ALL_ROLES)
    filters = {}
    for param in ("job_id", "equipment_unit_id", "operator_id", "status"):
        if request.args.get(param) is not None:
            filters[param] = request.args[param]
    page, limit, offset, total = list_paginated(store.assignments, filters,
                                                request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/assignments/<assignmentId>")
def get_assignment(assignmentId):
    require_roles(ALL_ROLES)
    return success_object(_get_assignment(assignmentId))


@bp.post("/v1/assignments/<assignmentId>/confirm")
def confirm_assignment(assignmentId):
    require_roles(["ProjectManager"])
    assignment = _get_assignment(assignmentId)
    if assignment["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED assignment can be confirmed")
    assignment["status"] = "CONFIRMED"
    touch(assignment)
    return success_object(assignment)


@bp.post("/v1/assignments/<assignmentId>/release")
def release_assignment(assignmentId):
    require_roles(["ProjectManager"])
    assignment = _get_assignment(assignmentId)
    if assignment["status"] != "CONFIRMED":
        raise invalid_state("Only a CONFIRMED assignment can be released")
    assignment["status"] = "RELEASED"
    touch(assignment)
    return success_object(assignment)


@bp.post("/v1/assignments/<assignmentId>/cancel")
def cancel_assignment(assignmentId):
    require_roles(["ProjectManager"])
    assignment = _get_assignment(assignmentId)
    if assignment["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise invalid_state("Only a SCHEDULED or CONFIRMED assignment can be cancelled")
    assignment["status"] = "CANCELLED"
    touch(assignment)
    return success_object(assignment)
