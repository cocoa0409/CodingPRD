"""AssignmentRecord routes (PRD §3.8): recordation with segregation of duties
and the register-rejection re-execution loop."""

from flask import Blueprint

import db as dbmod
import serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_CLIENT_SUSPENDED,
    ERR_INVENTOR_CLIENT_MISMATCH,
)
from middleware import require_roles, get_json_body, ALL_ROLES
from response import success_object, success_list_all
from services.common import (
    new_id, stamp_new, bump, get_application, get_assignment,
    client_of_application, check_allowed_fields, req_str, req_date,
    ensure_transition,
)

bp = Blueprint("assignments", __name__)


@bp.post("/applications/<application_id>/assignments")
def create_assignment(application_id):
    require_roles(["RecordsSpecialist"])
    app = get_application(application_id)
    body = get_json_body()
    # Existence (priority 4): each element of inventor_ids must resolve.
    inventor_ids = body.get("inventor_ids")
    if isinstance(inventor_ids, list):
        for inv_id in inventor_ids:
            if isinstance(inv_id, str):
                get_inventor_or_404(inv_id)
    # Body shape (priority 6).
    check_allowed_fields(body, {"assignee_name", "inventor_ids", "execution_date"})
    assignee_name = req_str(body, "assignee_name")
    if not isinstance(inventor_ids, list) or any(not isinstance(x, str) for x in inventor_ids):
        raise_err(ERR_INVALID_REQUEST, "inventor_ids must be an array of Inventor id strings")
    for inv_id in inventor_ids:
        get_inventor_or_404(inv_id)
    execution_date = req_date(body, "execution_date")
    # Business order: inventor-client membership (20), then suspended client (24).
    client = client_of_application(app)
    for inv_id in inventor_ids:
        inventor = dbmod.DB["inventors"][inv_id]
        if inventor["client_id"] != client["id"]:
            raise_err(ERR_INVENTOR_CLIENT_MISMATCH, "An inventor belongs to a different client")
    if client["status"] == "SUSPENDED":
        raise_err(ERR_CLIENT_SUSPENDED, "Client is SUSPENDED")
    rec = stamp_new({
        "id": new_id(),
        "application_id": app["id"],
        "assignee_name": assignee_name,
        "inventor_ids": list(inventor_ids),
        "execution_date": execution_date,
        "executed_by_user_id": None,
        "register_recordation_number": None,
        "status": "DRAFT",
    })
    dbmod.DB["assignments"][rec["id"]] = rec
    return success_object(serialize.assignment(rec), 201)


def get_inventor_or_404(inv_id):
    inventor = dbmod.DB["inventors"].get(inv_id)
    if inventor is None:
        raise_err(ERR_NOT_FOUND, f"Inventor not found: {inv_id}")
    return inventor


@bp.get("/applications/<application_id>/assignments")
def list_application_assignments(application_id):
    require_roles(ALL_ROLES)
    app = get_application(application_id)
    items = [a for a in dbmod.DB["assignments"].values() if a["application_id"] == app["id"]]
    items.sort(key=lambda r: r["created_at"])
    return success_list_all([serialize.assignment(r) for r in items])


@bp.get("/assignments/<assignment_id>")
def get_assignment_route(assignment_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.assignment(get_assignment(assignment_id)))


@bp.post("/assignments/<assignment_id>/execute")
def execute_assignment(assignment_id):
    user_id, _ = require_roles(["RecordsSpecialist"])
    rec = get_assignment(assignment_id)
    ensure_transition(rec, {"DRAFT", "RECORDATION_REJECTED"}, "assignments", "AssignmentRecord")
    rec["status"] = "EXECUTED"
    rec["executed_by_user_id"] = user_id
    bump(rec)
    return success_object(serialize.assignment(rec))


@bp.post("/assignments/<assignment_id>/record")
def record_assignment(assignment_id):
    user_id, _ = require_roles(["RecordsSpecialist"])
    rec = get_assignment(assignment_id)
    body = get_json_body()
    check_allowed_fields(body, {"register_recordation_number"})
    register_recordation_number = req_str(body, "register_recordation_number")
    ensure_transition(rec, {"EXECUTED"}, "assignments", "AssignmentRecord")
    if user_id == rec["executed_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Recorder must differ from the executor")
    rec["status"] = "RECORDED"
    rec["register_recordation_number"] = register_recordation_number
    bump(rec)
    return success_object(serialize.assignment(rec))


@bp.post("/assignments/<assignment_id>/record-rejection")
def record_rejection_assignment(assignment_id):
    require_roles(["RecordsSpecialist"])
    rec = get_assignment(assignment_id)
    ensure_transition(rec, {"EXECUTED"}, "assignments", "AssignmentRecord")
    rec["status"] = "RECORDATION_REJECTED"
    bump(rec)
    return success_object(serialize.assignment(rec))
