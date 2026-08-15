"""Loaner fleet program (PRD 3.6): loaner units and windowed assignments."""
from flask import Blueprint

from db import store, new_id, new_common, touch, parse_iso_date
from errors import ApiError
from middleware import get_context, require_roles
from response import ok, created, paginate
from services import workflow
from validation import (parse_body, no_body, require_path_entity, resolve_fk,
                        schema_field)

bp = Blueprint("loaners", __name__)

LOANER_ROLES = ["IntakeCoordinator", "RemanEngineer", "ServiceManager"]


@bp.post("/reman/loaner-units")
def create_loaner():
    uid, role, _ = get_context()
    require_roles(["ServiceManager"])
    body = parse_body({
        "serial_number": schema_field("string"),
        "model": schema_field("string"),
    }, allow_empty=False)
    for loaner in store.loaner_units.values():
        if loaner["serial_number"] == body["serial_number"]:
            raise ApiError("ERR_SERIAL_EXISTS", 409,
                           "serial_number already registered in the loaner fleet")
    loaner = {
        "id": new_id(),
        "serial_number": body["serial_number"],
        "model": body["model"],
        "status": "AVAILABLE",
    }
    new_common(loaner)
    store.loaner_units[loaner["id"]] = loaner
    return created(loaner)


@bp.get("/reman/loaner-units/<loaner_id>")
def get_loaner(loaner_id):
    uid, role, _ = get_context()
    require_roles(LOANER_ROLES)
    return ok(require_path_entity(store.loaner_units, loaner_id))


@bp.get("/reman/loaner-units/<loaner_id>/assignments")
def list_loaner_assignments(loaner_id):
    uid, role, _ = get_context()
    require_roles(LOANER_ROLES)
    require_path_entity(store.loaner_units, loaner_id)
    rows = workflow.assignments_of_loaner(loaner_id)
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.post("/reman/loaner-units/<loaner_id>/assignments")
def create_assignment(loaner_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    loaner = require_path_entity(store.loaner_units, loaner_id)
    body = parse_body({
        "reman_order_id": schema_field("string"),
        "start_date": schema_field("date"),
        "end_date": schema_field("date"),
    }, allow_empty=False)
    resolve_fk(store.orders, body["reman_order_id"], "reman_order_id")
    # Priority 7 (exclusivity) surfaces before priority 8 (temporal window).
    if workflow.loaner_window_overlaps(loaner["id"], body["start_date"],
                                       body["end_date"]):
        raise ApiError("ERR_LOANER_OVERLAP", 409,
                       "Window overlaps an existing non-cancelled assignment")
    if parse_iso_date(body["end_date"]) <= parse_iso_date(body["start_date"]):
        raise ApiError("ERR_INVALID_WINDOW", 422,
                       "end_date must fall strictly after start_date")
    assignment = {
        "id": new_id(),
        "loaner_unit_id": loaner["id"],
        "reman_order_id": body["reman_order_id"],
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "status": "RESERVED",
    }
    new_common(assignment)
    store.loaner_assignments[assignment["id"]] = assignment
    return created(assignment)


@bp.get("/reman/loaner-assignments")
def list_assignments():
    uid, role, _ = get_context()
    require_roles(LOANER_ROLES)
    rows = list(store.loaner_assignments.values())
    rows = paginate.filter(rows, "reman_order_id")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/reman/loaner-assignments/<assignment_id>")
def get_assignment(assignment_id):
    uid, role, _ = get_context()
    require_roles(LOANER_ROLES)
    return ok(require_path_entity(store.loaner_assignments, assignment_id))


@bp.post("/reman/loaner-assignments/<assignment_id>/checkout")
def checkout_assignment(assignment_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    assignment = require_path_entity(store.loaner_assignments, assignment_id)
    no_body()
    if assignment["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "checkout exists only from status RESERVED")
    loaner = store.loaner_units.get(assignment["loaner_unit_id"])
    if loaner is None or loaner["status"] != "AVAILABLE":
        raise ApiError("ERR_LOANER_UNAVAILABLE", 409,
                       "LoanerUnit is not AVAILABLE")
    if store.clock.date() < parse_iso_date(assignment["start_date"]):
        raise ApiError("ERR_LOANER_WINDOW_FUTURE", 422,
                       "Checkout may not precede the window start_date")
    assignment["status"] = "CHECKED_OUT"
    touch(assignment)
    loaner["status"] = "CHECKED_OUT"
    touch(loaner)
    return ok(assignment)


@bp.post("/reman/loaner-assignments/<assignment_id>/return")
def return_assignment(assignment_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    assignment = require_path_entity(store.loaner_assignments, assignment_id)
    body = parse_body({
        "expected_assignment_version": schema_field("version"),
    }, allow_empty=False)
    if assignment["status"] != "CHECKED_OUT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "return exists only from status CHECKED_OUT")
    if int(body["expected_assignment_version"]) != assignment["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_assignment_version does not match the "
                       "assignment's current version")
    assignment["status"] = "RETURNED"
    touch(assignment)
    loaner = store.loaner_units.get(assignment["loaner_unit_id"])
    if loaner is not None:
        loaner["status"] = "AVAILABLE"
        touch(loaner)
    return ok(assignment)


@bp.post("/reman/loaner-assignments/<assignment_id>/extend")
def extend_assignment(assignment_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    assignment = require_path_entity(store.loaner_assignments, assignment_id)
    body = parse_body({"new_end_date": schema_field("date")}, allow_empty=False)
    if assignment["status"] not in ("RESERVED", "CHECKED_OUT"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "extend exists only from status RESERVED or CHECKED_OUT")
    if workflow.loaner_window_overlaps(assignment["loaner_unit_id"],
                                       assignment["start_date"],
                                       body["new_end_date"],
                                       exclude_id=assignment["id"]):
        raise ApiError("ERR_LOANER_OVERLAP", 409,
                       "Extended window overlaps an existing non-cancelled assignment")
    if parse_iso_date(body["new_end_date"]) <= parse_iso_date(assignment["start_date"]):
        raise ApiError("ERR_INVALID_WINDOW", 422,
                       "new_end_date must fall strictly after start_date")
    assignment["end_date"] = body["new_end_date"]
    touch(assignment)
    return ok(assignment)


@bp.post("/reman/loaner-assignments/<assignment_id>/cancel")
def cancel_assignment(assignment_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    assignment = require_path_entity(store.loaner_assignments, assignment_id)
    no_body()
    if assignment["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "cancel exists only from status RESERVED")
    assignment["status"] = "CANCELLED"
    touch(assignment)
    return ok(assignment)
