"""Milestone endpoints (PRD 3.7)."""
from flask import Blueprint, request

from common import (as_int, as_str, get_body, init_common, parse_pagination,
                    require, sort_by_creation)
from db import db
from errors import ERR_INVALID_REQUEST, raise_error
from lookups import get_goal, get_milestone
from middleware import require_roles
from response import paginated, success
from serializers import serialize

bp = Blueprint("milestones", __name__)

VALID_THRESHOLDS = {25, 50, 75, 100}


@bp.route("/wm/milestones", methods=["POST"])
@require_roles("ProgramAdmin", "Coach")
def create_milestone():
    body = get_body()
    goal_id = as_str(require(body, "goal_id"), "goal_id")
    threshold = as_int(require(body, "threshold_pct"), "threshold_pct")
    if threshold not in VALID_THRESHOLDS:
        raise_error(ERR_INVALID_REQUEST, "threshold_pct must be one of 25,50,75,100")

    goal = get_goal(goal_id)

    milestone = {
        "goal_id": goal_id,
        "enrollment_id": goal["enrollment_id"],
        "threshold_pct": threshold,
        "achieved_at_utc": None,
        "achieved_weight_kg": None,
        "status": "PENDING",
    }
    init_common(milestone)
    db.milestones[milestone["id"]] = milestone
    return success(serialize(milestone), 201)


@bp.route("/wm/milestones", methods=["GET"])
@require_roles("ProgramAdmin", "Clinician", "Coach", "Member")
def list_milestones():
    limit, offset = parse_pagination()
    items = list(db.milestones.values())
    goal_id = request.args.get("goal_id")
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    if goal_id is not None:
        items = [m for m in items if m["goal_id"] == goal_id]
    if enrollment_id is not None:
        items = [m for m in items if m["enrollment_id"] == enrollment_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated([serialize(m) for m in page], limit, offset, total)


@bp.route("/wm/milestones/<milestone_id>", methods=["GET"])
@require_roles("ProgramAdmin", "Clinician", "Coach", "Member")
def get_one_milestone(milestone_id):
    return success(serialize(get_milestone(milestone_id)), 200)
