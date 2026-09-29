"""PunchItem endpoints: commissioning defects, verification and waiver (PRD §3.9)."""

from flask import Blueprint

import helpers
import serializers
from auth import (ALL_ROLES, ROLE_ACCESSIBILITY, ROLE_CURATOR, ROLE_FABRICATION_LEAD,
                  ROLE_MUSEUM_OPERATIONS, ROLE_PROJECT_MANAGER, caller_id, caller_role,
                  check_segregation, endpoint)
from envelope import list_response, object_response, pagination, query_filter
from errors import ApiError
from helpers import touch
from store import db, new_row, order_created
from validate import bad, body_object, v_enum, v_id, v_str

bp = Blueprint("punch", __name__)

SEVERITIES = ("BLOCKING", "MAJOR", "MINOR")


@bp.route("/exhibit-projects/<pid>/punch-items", methods=["POST"])
@endpoint(roles=[ROLE_MUSEUM_OPERATIONS, ROLE_CURATOR, ROLE_PROJECT_MANAGER, ROLE_ACCESSIBILITY])
def create_punch_item(pid):
    project = helpers.get_project(pid)
    body = body_object()
    severity = v_enum(body, "severity", SEVERITIES)
    description = v_str(body, "description", 1, 500, non_blank=True)
    interactive_id = v_id(body, "interactive_id", required=False, default=None)
    case_id = v_id(body, "case_id", required=False, default=None)
    if interactive_id is not None and case_id is not None:
        bad("A punch item may name at most one subject.")

    # Step 5: the case 404 precedes the interactive 404 (PRD §2.5 ordering).
    case = helpers.get_case(case_id) if case_id is not None else None
    interactive = helpers.get_interactive(interactive_id) if interactive_id is not None else None
    helpers.require_same_project(project, case)
    helpers.require_same_project(project, interactive)

    helpers.require_phase(project, ("COMMISSIONING",))

    item = new_row("punch_items", {
        "project_id": project["id"],
        "interactive_id": interactive_id,
        "case_id": case_id,
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "raised_by_role": caller_role(),
        "raised_by_user_id": caller_id(),
        "verified_by_user_id": None,
        "verification_note": None,
        "waiver_reason": None,
        "verified_at": None,
    })
    db.punch_items[item["id"]] = item
    return object_response(serializers.punch_json(item), 201)


@bp.route("/exhibit-projects/<pid>/punch-items", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_project_punch_items(pid):
    project = helpers.get_project(pid)
    limit, offset = pagination()
    status = query_filter("status")
    severity = query_filter("severity")
    rows = helpers.rows_of_project(db.punch_items, project["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    return list_response(rows, serializers.punch_json, limit, offset)


@bp.route("/punch-items", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_punch_items():
    limit, offset = pagination()
    project_id = query_filter("project_id")
    interactive_id = query_filter("interactive_id")
    case_id = query_filter("case_id")
    status = query_filter("status")
    severity = query_filter("severity")
    rows = sorted(db.punch_items.values(), key=order_created)
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if interactive_id is not None:
        rows = [r for r in rows if r["interactive_id"] == interactive_id]
    if case_id is not None:
        rows = [r for r in rows if r["case_id"] == case_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    return list_response(rows, serializers.punch_json, limit, offset)


@bp.route("/punch-items/<item_id>", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def get_punch_item(item_id):
    item = helpers.get_punch_item(item_id)
    return object_response(serializers.punch_json(item))


@bp.route("/punch-items/<item_id>/verify", methods=["POST"])
@endpoint(roles=[ROLE_FABRICATION_LEAD, ROLE_PROJECT_MANAGER])
def verify_punch_item(item_id):
    item = helpers.get_punch_item(item_id)
    project = helpers.owning_project(item)
    # Step 3: the caller may not be the person who raised the defect.
    check_segregation(item["raised_by_user_id"])
    body = body_object()
    note = v_str(body, "verification_note", 1, None, non_blank=True)

    helpers.require_phase(project, ("COMMISSIONING", "CLOSEOUT"))
    if item["status"] != "OPEN":
        raise ApiError("ERR_INVALID_PUNCH_STATE")

    item["status"] = "VERIFIED"
    item["verified_by_user_id"] = caller_id()
    item["verification_note"] = note
    item["verified_at"] = db.now()
    touch(item)
    return object_response(serializers.punch_json(item))


@bp.route("/punch-items/<item_id>/waive", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER])
def waive_punch_item(item_id):
    item = helpers.get_punch_item(item_id)
    project = helpers.owning_project(item)
    check_segregation(item["raised_by_user_id"])
    body = body_object()
    reason = v_str(body, "waiver_reason", 1, None, non_blank=True)

    helpers.require_phase(project, ("COMMISSIONING", "CLOSEOUT"))
    if item["status"] != "OPEN":
        raise ApiError("ERR_INVALID_PUNCH_STATE")
    # A BLOCKING defect can never be waived, only verified.
    if item["severity"] not in ("MAJOR", "MINOR"):
        raise ApiError("ERR_INVALID_PUNCH_STATE", "A BLOCKING defect can never be waived.")

    item["status"] = "WAIVED"
    item["waiver_reason"] = reason
    item["verified_at"] = db.now()
    touch(item)
    return object_response(serializers.punch_json(item))
