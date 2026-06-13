"""Goal endpoints (PRD 3.6)."""
from flask import Blueprint, request

from common import (as_enum, as_number, as_str, get_body, init_common,
                    parse_pagination, require, sort_by_creation)
from db import db
from errors import (ERR_INVALID_REQUEST, ERR_TARGET_NOT_BELOW_BASELINE,
                    raise_error)
from lookups import get_enrollment, get_goal, get_member
from middleware import require_roles
from response import paginated, success
from serializers import serialize
import calculations as calc

bp = Blueprint("goals", __name__)

KINDS = {"PRIMARY", "SECONDARY"}


@bp.route("/wm/goals", methods=["POST"])
@require_roles("ProgramAdmin", "Coach")
def create_goal():
    body = get_body()
    enrollment_id = as_str(require(body, "enrollment_id"), "enrollment_id")
    kind = as_enum(require(body, "kind"), "kind", KINDS)
    target_weight_kg = as_number(require(body, "target_weight_kg"), "target_weight_kg")

    enrollment = get_enrollment(enrollment_id)
    member = get_member(enrollment["member_id"])

    baseline = member["baseline_weight_kg"]
    if target_weight_kg <= 0 or baseline is None or target_weight_kg >= baseline:
        raise_error(ERR_TARGET_NOT_BELOW_BASELINE,
                    "target_weight_kg must be > 0 and strictly below baseline")

    goal = {
        "enrollment_id": enrollment_id,
        "member_id": enrollment["member_id"],
        "kind": kind,
        "target_weight_kg": target_weight_kg,
        "progress_pct": 0,
        "status": "OPEN",
    }
    init_common(goal)
    # progress computed from current member state at creation
    goal["progress_pct"] = calc.compute_goal_progress_pct(
        baseline, member["latest_weight_kg"], target_weight_kg
    )
    db.goals[goal["id"]] = goal
    return success(serialize(goal), 201)


@bp.route("/wm/goals", methods=["GET"])
@require_roles("ProgramAdmin", "Clinician", "Coach", "Member")
def list_goals():
    limit, offset = parse_pagination()
    items = list(db.goals.values())
    enrollment_id = request.args.get("enrollment_id")
    member_id = request.args.get("member_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    if enrollment_id is not None:
        items = [g for g in items if g["enrollment_id"] == enrollment_id]
    if member_id is not None:
        items = [g for g in items if g["member_id"] == member_id]
    if kind is not None:
        items = [g for g in items if g["kind"] == kind]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated([serialize(g) for g in page], limit, offset, total)


@bp.route("/wm/goals/<goal_id>", methods=["GET"])
@require_roles("ProgramAdmin", "Clinician", "Coach", "Member")
def get_one_goal(goal_id):
    return success(serialize(get_goal(goal_id)), 200)
