"""Goal endpoints (PRD §3.3)."""

from flask import Blueprint, request

import errors
from errors import ApiError
from db import db
from response import success, list_success
from middleware import require_roles, ALL_ROLES
from validation import get_body, require_str, require_int, bad
from services.common import new_record, touch, lookup, paginate, sorted_by_created
from services import serialize, engine

bp = Blueprint("goals", __name__)


@bp.route("/clinic/plans-of-care/<plan_id>/goals", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_goals(plan_id, user_id=None, role=None):
    lookup(db.plans_of_care, plan_id)
    items = [g for g in db.goals.values() if g["plan_of_care_id"] == plan_id]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return list_success([serialize.goal(g) for g in page], limit, offset, total)


@bp.route("/clinic/plans-of-care/<plan_id>/goals", methods=["POST"])
@require_roles("Evaluator", "Therapist")
def add_goal(plan_id, user_id=None, role=None):
    plan = lookup(db.plans_of_care, plan_id)
    body = get_body()
    description = require_str(body, "description")
    weight = require_int(body, "weight", minimum=1)
    baseline = require_int(body, "baseline_pct", minimum=0, maximum=100)
    target = require_int(body, "target_pct", minimum=0, maximum=100)
    # target_pct must strictly exceed baseline_pct.
    if target <= baseline:
        raise bad("target_pct must be strictly greater than baseline_pct.")
    # Goals authored while plan is DRAFT or ACTIVE.
    if plan["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Goals may be added only while the plan is DRAFT or ACTIVE.")
    rec = new_record({
        "plan_of_care_id": plan_id,
        "description": description,
        "weight": weight,
        "baseline_pct": baseline,
        "target_pct": target,
        "latest_progress_pct": baseline,
        "status": "OPEN",
    })
    db.goals[rec["id"]] = rec
    # PlanOfCare.goal_count += 1; overall_progress_pct recomputed.
    engine.recompute_goal_count(plan)
    engine.reconcile_plan_progress(plan)
    return success(serialize.goal(rec), status=201)


@bp.route("/clinic/goals/<goal_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_goal(goal_id, user_id=None, role=None):
    rec = lookup(db.goals, goal_id)
    return success(serialize.goal(rec), status=200)


@bp.route("/clinic/goals/<goal_id>/discontinue", methods=["POST"])
@require_roles("Therapist", "Evaluator")
def discontinue_goal(goal_id, user_id=None, role=None):
    rec = lookup(db.goals, goal_id)
    if rec["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Goal must be OPEN to discontinue.")
    rec["status"] = "DISCONTINUED"
    touch(rec)
    plan = db.plans_of_care.get(rec["plan_of_care_id"])
    if plan is not None:
        engine.reconcile_plan_progress(plan)
    return success(serialize.goal(rec), status=200)


@bp.route("/clinic/goals/<goal_id>/progress-entries", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_progress_entries(goal_id, user_id=None, role=None):
    lookup(db.goals, goal_id)
    items = [e for e in db.goal_progress_entries.values() if e["goal_id"] == goal_id]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return list_success(
        [serialize.goal_progress_entry(e) for e in page], limit, offset, total
    )
