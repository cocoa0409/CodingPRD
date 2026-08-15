"""ReviewAssignment endpoints (OCC-guarded creation)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CYCLE_NOT_FOUND,
    ERR_REVIEWER_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_STALE_CYCLE_VERSION,
    ERR_CYCLE_NOT_ASSIGNABLE,
    ERR_LICENSE_STATE_MISMATCH,
    ERR_LICENSE_WINDOW_INSUFFICIENT,
    ERR_REVIEWER_CAPACITY_EXCEEDED,
    ERR_INVALID_STATE_TRANSITION,
)
from middleware import (
    require_roles, get_json_body, require_fields, reject_unknown_fields,
    require_string, require_int, parse_pagination, paginate,
)
from response import success_object, success_list
from services.core import (
    license_for_state, parse_date, refresh_reviewer_count, end_assignment,
)

bp = Blueprint("assignments", __name__)

READ_ROLES = ("PlatformAdmin", "ReviewCoordinator", "Reviewer", "ChiefReviewer", "Applicant")


@bp.post("/plan-review/assignments")
def create_assignment():
    require_roles("ReviewCoordinator")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {"cycle_id", "reviewer_id", "expected_cycle_version"})
    require_fields(body, ["cycle_id", "reviewer_id", "expected_cycle_version"])
    cycle_id = require_string(body, "cycle_id")
    reviewer_id = require_string(body, "reviewer_id")
    expected_cycle_version = require_int(body, "expected_cycle_version")

    # existence: body FKs (cycle_id, then reviewer_id)
    cycle = db.cycles.get(cycle_id)
    if cycle is None:
        raise ApiError(ERR_CYCLE_NOT_FOUND, 404, "No review cycle with the given id")
    reviewer = db.reviewers.get(reviewer_id)
    if reviewer is None:
        raise ApiError(ERR_REVIEWER_NOT_FOUND, 404, "No reviewer with the given id")

    # state layer: OCC check runs first (§2.9), then cycle assignability
    if expected_cycle_version != cycle["version"]:
        raise ApiError(ERR_STALE_CYCLE_VERSION, 412,
                       "expected_cycle_version does not equal the cycle's current version")
    if cycle["status"] not in ("OPEN", "IN_REVIEW"):
        raise ApiError(ERR_CYCLE_NOT_ASSIGNABLE, 409,
                       "Assignment attempted on a cycle not in OPEN or IN_REVIEW")

    # regulatory: license covering pinned state with expires_on >= date(cycle.due_at)
    engagement = db.engagements[cycle["engagement_id"]]
    lic = license_for_state(reviewer, engagement["pinned_state_code"])
    if lic is None:
        raise ApiError(ERR_LICENSE_STATE_MISMATCH, 422,
                       "Reviewer holds no license covering the engagement's pinned state")
    if parse_date(lic["expires_on"]) < cycle["due_at"].date():
        raise ApiError(ERR_LICENSE_WINDOW_INSUFFICIENT, 422,
                       "Reviewer's state license expires before the cycle due date")

    # capacity gate: reject at count >= max (inclusive boundary)
    refresh_reviewer_count(reviewer)
    if reviewer["active_assignment_count"] >= reviewer["max_concurrent_assignments"]:
        raise ApiError(ERR_REVIEWER_CAPACITY_EXCEEDED, 409,
                       "Reviewer is at maximum concurrent assignments")

    # supersede any existing ACTIVE assignment on this cycle (reassignment)
    for a in list(db.assignments.values()):
        if a["cycle_id"] == cycle["id"] and a["status"] == "ACTIVE":
            end_assignment(a, "RELEASED")

    now = db.clock_now()
    entity = db.stamp_new({
        "cycle_id": cycle["id"],
        "reviewer_id": reviewer["id"],
        "assigned_at": now,
        "ended_at": None,
        "status": "ACTIVE",
    })
    db.assignments[entity["id"]] = entity

    # assignee count increments (via aggregate refresh)
    refresh_reviewer_count(reviewer)
    db.touch(reviewer)

    # first assignment walks cycle OPEN -> IN_REVIEW; success bumps cycle version
    if cycle["status"] == "OPEN":
        cycle["status"] = "IN_REVIEW"
    db.touch(cycle)

    return success_object(db.serialize(entity), status=201)


@bp.get("/plan-review/assignments")
def list_assignments():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.assignments.values())
    cycle_id = request.args.get("cycle_id")
    reviewer_id = request.args.get("reviewer_id")
    status = request.args.get("status")
    if cycle_id is not None:
        items = [a for a in items if a["cycle_id"] == cycle_id]
    if reviewer_id is not None:
        items = [a for a in items if a["reviewer_id"] == reviewer_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([db.serialize(a) for a in page], limit, offset, total)


@bp.get("/plan-review/assignments/<aid>")
def get_assignment(aid):
    require_roles(*READ_ROLES)
    a = db.assignments.get(aid)
    if a is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND, 404, "No review assignment with the given id")
    return success_object(db.serialize(a))


@bp.post("/plan-review/assignments/<aid>/release")
def release_assignment(aid):
    require_roles("ReviewCoordinator")
    get_json_body(required=False)
    a = db.assignments.get(aid)
    if a is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND, 404, "No review assignment with the given id")
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Assignment is not ACTIVE")
    end_assignment(a, "RELEASED")
    return success_object(db.serialize(a))
