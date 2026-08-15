"""ServiceAgency and ServiceAssignment endpoints (PRD 3.7)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_AGENCY_AT_CAPACITY,
    ERR_AGENCY_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_OPEN,
    ERR_INVALID_REQUEST,
    HTTP_STATUS,
)
from middleware import require_roles
from response import success_object
from routes.common import (
    paginate,
    resolve_agency,
    resolve_assignment,
    resolve_project,
    serialize,
)
from services import workflow
from services.validate import json_body, req_int, req_str

bp = Blueprint("agencies", __name__)

AGENCY_READ_ROLES = ("PlatformAdmin", "ProjectManager", "ServiceManager")
ASSIGNMENT_READ_ROLES = ("PlatformAdmin", "ProjectManager", "ServiceManager")
JURISDICTIONS = ("CITY_HEALTH", "COUNTY_HEALTH", "STATE_HEALTH")


@bp.route("/service-agencies", methods=["POST"])
@require_roles("ServiceManager", "PlatformAdmin")
def create_agency(_user_id=None, _role=None):
    body = json_body(required=True)
    agency_name = req_str(body, "agency_name")
    covered = body.get("covered_jurisdictions")
    if not isinstance(covered, list) or any(
        not isinstance(c, str) or c not in JURISDICTIONS for c in covered
    ):
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            "covered_jurisdictions must be an array of jurisdiction codes",
        )
    capacity = req_int(body, "capacity", min_value=1)
    agency = db.stamp_new({
        "agency_name": agency_name,
        "covered_jurisdictions": list(covered),
        "capacity": capacity,
        "open_assignment_count": 0,
        "status": "ACTIVE",
    })
    db.agencies[agency["id"]] = agency
    # A newly available agency may release deferred commissioning bubble-ups.
    workflow.retry_deferred_commissions()
    return success_object(serialize(agency), 201)


@bp.route("/service-agencies", methods=["GET"])
@require_roles(*AGENCY_READ_ROLES)
def list_agencies(_user_id=None, _role=None):
    status = request.args.get("status")
    records = list(db.agencies.values())
    if status is not None:
        records = [a for a in records if a["status"] == status]
    return paginate(records)


@bp.route("/service-agencies/<agencyId>", methods=["GET"])
@require_roles(*AGENCY_READ_ROLES)
def get_agency(agencyId, _user_id=None, _role=None):
    agency = resolve_agency(agencyId)
    return success_object(serialize(agency), 200)


@bp.route("/design-build-projects/<id>/service-assignments", methods=["GET"])
@require_roles(*ASSIGNMENT_READ_ROLES)
def list_assignments(id, _user_id=None, _role=None):
    project = resolve_project(id)
    status = request.args.get("status")
    agency_id = request.args.get("agency_id")
    records = [a for a in db.assignments.values() if a["project_id"] == project["id"]]
    if status is not None:
        records = [a for a in records if a["status"] == status]
    if agency_id is not None:
        records = [a for a in records if a["agency_id"] == agency_id]
    return paginate(records)


@bp.route("/design-build-projects/<id>/service-assignments/<assignmentId>", methods=["GET"])
@require_roles(*ASSIGNMENT_READ_ROLES)
def get_assignment(id, assignmentId, _user_id=None, _role=None):
    project = resolve_project(id)
    assignment = resolve_assignment(project, assignmentId)
    return success_object(serialize(assignment), 200)


@bp.route("/design-build-projects/<id>/service-assignments/<assignmentId>/close", methods=["POST"])
@require_roles("ServiceManager")
def close_assignment(id, assignmentId, _user_id=None, _role=None):
    project = resolve_project(id)
    assignment = resolve_assignment(project, assignmentId)
    if assignment["status"] != "OPEN":
        raise ApiError(
            ERR_ASSIGNMENT_NOT_OPEN, HTTP_STATUS[ERR_ASSIGNMENT_NOT_OPEN],
            "Close requires ServiceAssignment in OPEN",
        )
    assignment["status"] = "CLOSED"
    db.touch(assignment)
    agency = db.agencies.get(assignment["agency_id"])
    if agency is not None and agency["open_assignment_count"] > 0:
        agency["open_assignment_count"] -= 1
        db.touch(agency)
    # Freed capacity may release a deferred commissioning bubble-up.
    workflow.retry_deferred_commissions()
    return success_object(serialize(assignment), 200)


@bp.route("/design-build-projects/<id>/service-assignments/<assignmentId>/transfer", methods=["POST"])
@require_roles("ServiceManager")
def transfer_assignment(id, assignmentId, _user_id=None, _role=None):
    project = resolve_project(id)
    assignment = resolve_assignment(project, assignmentId)
    body = json_body(required=True)
    target_id = req_str(body, "target_agency_id")
    target = db.agencies.get(target_id)
    if target is None:
        raise ApiError(
            ERR_AGENCY_NOT_FOUND, HTTP_STATUS[ERR_AGENCY_NOT_FOUND],
            "ServiceAgency not found",
        )
    if assignment["status"] != "OPEN":
        raise ApiError(
            ERR_ASSIGNMENT_NOT_OPEN, HTTP_STATUS[ERR_ASSIGNMENT_NOT_OPEN],
            "Transfer requires ServiceAssignment in OPEN",
        )
    if (
        target["status"] != "ACTIVE"
        or int(target["open_assignment_count"]) >= int(target["capacity"])
    ):
        raise ApiError(
            ERR_AGENCY_AT_CAPACITY, HTTP_STATUS[ERR_AGENCY_AT_CAPACITY],
            "Target agency open_assignment_count >= capacity",
        )
    original_agency = db.agencies.get(assignment["agency_id"])
    assignment["status"] = "TRANSFERRED"
    db.touch(assignment)
    if original_agency is not None and original_agency["open_assignment_count"] > 0:
        original_agency["open_assignment_count"] -= 1
        db.touch(original_agency)
    new_assignment = db.stamp_new({
        "project_id": project["id"],
        "agency_id": target["id"],
        "opened_at": db.now_iso(),
        "status": "OPEN",
    })
    db.assignments[new_assignment["id"]] = new_assignment
    target["open_assignment_count"] = int(target["open_assignment_count"]) + 1
    db.touch(target)
    workflow.retry_deferred_commissions()
    return success_object(serialize(assignment), 200)
