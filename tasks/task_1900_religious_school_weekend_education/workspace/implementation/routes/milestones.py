"""Milestone endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from errors import (
    ApiError, invalid_request, invalid_state, ownership_mismatch,
    ERR_MILESTONE_NOT_ELIGIBLE, ERR_VOLUNTEER_REQUIREMENT_UNMET,
)
from services.core import (
    public, get_milestone, reevaluate_milestone, parse_date, touch,
)

bp = Blueprint("milestones", __name__)


@bp.route("/school/milestones/<milestone_id>", methods=["GET"])
def get_milestone_endpoint(milestone_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    rec = get_milestone(milestone_id)
    if role == "Parent" and rec["family_id"] != user_id:
        raise ownership_mismatch()
    return success_object(public(rec))


@bp.route("/school/milestones", methods=["GET"])
def list_milestones():
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    limit, offset = parse_pagination(request.args)
    student_id = request.args.get("student_id")
    family_id = request.args.get("family_id")
    school_year_id = request.args.get("school_year_id")
    status = request.args.get("status")

    items = list(store.milestones.values())
    if role == "Parent":
        if family_id is not None and family_id != user_id:
            raise ownership_mismatch()
        items = [m for m in items if m["family_id"] == user_id]
    if student_id is not None:
        items = [m for m in items if m["student_id"] == student_id]
    if family_id is not None:
        items = [m for m in items if m["family_id"] == family_id]
    if school_year_id is not None:
        items = [m for m in items if m["school_year_id"] == school_year_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([public(m) for m in page], limit, offset, total)


@bp.route("/school/milestones/<milestone_id>/evaluate", methods=["POST"])
def evaluate_milestone(milestone_id):
    require_roles(["SchoolAdmin"])
    rec = get_milestone(milestone_id)
    reevaluate_milestone(rec)
    return success_object(public(rec))


@bp.route("/school/milestones/<milestone_id>/schedule", methods=["POST"])
def schedule_milestone(milestone_id):
    require_roles(["SchoolAdmin"])
    rec = get_milestone(milestone_id)
    body = request.get_json(silent=True) or {}
    ceremony_date = body.get("ceremony_date")
    if ceremony_date is not None:
        if not isinstance(ceremony_date, str):
            raise invalid_request("ceremony_date must be a string date")
        parse_date(ceremony_date, "ceremony_date")

    # gate 1: ELIGIBLE
    if rec["status"] != "ELIGIBLE":
        if rec["status"] in ("TRACKING", "SCHEDULED", "COMPLETED"):
            raise ApiError(ERR_MILESTONE_NOT_ELIGIBLE, 409, "Milestone is not ELIGIBLE")
        raise invalid_state("Milestone is not in a schedulable state")

    # gate 2: family VolunteerCommitment for this year must be FULFILLED
    commitment = None
    for c in store.commitments.values():
        if c["family_id"] == rec["family_id"] and c["school_year_id"] == rec["school_year_id"]:
            commitment = c
            break
    if commitment is None or commitment["status"] != "FULFILLED":
        raise ApiError(ERR_VOLUNTEER_REQUIREMENT_UNMET, 409, "Volunteer commitment is not FULFILLED")

    rec["status"] = "SCHEDULED"
    if ceremony_date is not None:
        rec["ceremony_date"] = ceremony_date
    touch(rec)
    return success_object(public(rec))


@bp.route("/school/milestones/<milestone_id>/complete", methods=["POST"])
def complete_milestone(milestone_id):
    require_roles(["SchoolAdmin"])
    rec = get_milestone(milestone_id)
    if rec["status"] != "SCHEDULED":
        raise invalid_state("Milestone is not SCHEDULED")
    rec["status"] = "COMPLETED"
    touch(rec)
    return success_object(public(rec))
