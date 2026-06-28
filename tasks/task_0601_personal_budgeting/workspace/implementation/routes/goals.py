"""Goal + GoalContribution routes: create, get, list, patch, contribute, abandon."""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import (get_body, require_str, require_int,
                     enforce_household_access, paginate_and_respond)
from lookups import get_household, get_goal, get_contribution
from services.reconcile import (recompute_goal_funded, recompute_category,
                                recompute_posture, touch)

bp = Blueprint("goals", __name__)


def _evaluate_goal_status(goal):
    """ACTIVE -> FUNDED when funded_cents >= target_cents (boundary funds)."""
    if goal["status"] == "ACTIVE" and goal["funded_cents"] >= goal["target_cents"]:
        goal["status"] = "FUNDED"
        touch(goal)


@bp.route("/households/<household_id>/goals", methods=["POST"])
@require_roles("HouseholdOwner")
def create_goal(household_id):
    h = get_household(household_id)
    enforce_household_access(household_id)
    body = get_body()
    name = require_str(body, "name")
    target = require_int(body, "target_cents")
    funding_category_id = require_str(body, "funding_category_id")

    # Reference: funding category exists and belongs to household.
    cat = db.budget_categories.get(funding_category_id)
    if cat is None or cat["household_id"] != household_id:
        raise errors.reference_not_found("funding_category_id not found in household")

    # target_cents must be > 0.
    if target <= 0:
        raise errors.ApiError(errors.ERR_GOAL_TARGET_BELOW_FUNDED, 422,
                              "target_cents must be greater than zero")

    with lock:
        gid = new_id()
        ts = now_ts()
        goal = {
            "id": gid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "household_id": household_id,
            "name": name,
            "target_cents": target,
            "funded_cents": 0,
            "funding_category_id": funding_category_id,
            "status": "ACTIVE",
        }
        db.goals[gid] = goal
    return success(serializers.goal(goal), status=201)


@bp.route("/households/goals/<goal_id>", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def get_goal_route(goal_id):
    g = get_goal(goal_id)
    enforce_household_access(g["household_id"])
    return success(serializers.goal(g), status=200)


@bp.route("/households/goals", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def list_goals():
    household_id = request.args.get("household_id")
    status = request.args.get("status")
    funding_category_id = request.args.get("funding_category_id")
    items = list(db.goals.values())
    if household_id is not None:
        items = [g for g in items if g["household_id"] == household_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    if funding_category_id is not None:
        items = [g for g in items if g["funding_category_id"] == funding_category_id]
    return paginate_and_respond(items, serializers.goal)


@bp.route("/households/<household_id>/goals/<goal_id>", methods=["PATCH"])
@require_roles("HouseholdOwner")
def patch_goal(household_id, goal_id):
    h = get_household(household_id)
    g = get_goal(goal_id)
    enforce_household_access(household_id)
    if g["household_id"] != household_id:
        raise errors.not_found("Goal not found in household")
    body = get_body()
    target = require_int(body, "target_cents")

    # target must be > 0 and strictly above current funded_cents.
    if target <= 0 or target <= g["funded_cents"]:
        raise errors.ApiError(errors.ERR_GOAL_TARGET_BELOW_FUNDED, 422,
                              "target_cents must exceed current funded amount")

    with lock:
        g["target_cents"] = target
        touch(g)
        # Raising target above funded reopens FUNDED -> ACTIVE.
        if g["status"] == "FUNDED" and target > g["funded_cents"]:
            g["status"] = "ACTIVE"
            touch(g)
    return success(serializers.goal(g), status=200)


@bp.route("/households/<household_id>/goals/<goal_id>/contribute", methods=["POST"])
@require_roles("HouseholdOwner", "HouseholdMember")
def contribute(household_id, goal_id):
    h = get_household(household_id)
    g = get_goal(goal_id)
    enforce_household_access(household_id)
    if g["household_id"] != household_id:
        raise errors.not_found("Goal not found in household")

    body = get_body()
    # Parse type/presence early (needed to evaluate the envelope check); the
    # value-domain (positive) check is deferred to its §2.7 priority below.
    amount = require_int(body, "amount_cents")

    cat = db.budget_categories.get(g["funding_category_id"])

    # Frozen guard (priority 7).
    if h["posture"] == "FROZEN":
        raise errors.ApiError(errors.ERR_HOUSEHOLD_FROZEN, 409, "Household is frozen")
    # Funding category must belong to current OPEN period (priority 8).
    cur = h.get("current_period_id")
    if cat is None or cat["budget_period_id"] != cur:
        raise errors.ApiError(errors.ERR_CATEGORY_PERIOD_MISMATCH, 409,
                              "Funding category not in current period")
    # Value-domain check (priority 15) sits after the business guards.
    if amount <= 0:
        raise errors.invalid_request("amount_cents must be positive")
    # Insufficient envelope (priority 11; checked BEFORE applying).
    if cat["available_cents"] < amount:
        raise errors.ApiError(errors.ERR_INSUFFICIENT_ENVELOPE, 422,
                              "Funding envelope cannot cover contribution")

    with lock:
        cid = new_id()
        ts = now_ts()
        contribution = {
            "id": cid,
            "created_at": ts,
            "_seq": db.next_seq(),
            "goal_id": goal_id,
            "amount_cents": amount,
            "reversed": False,
        }
        db.goal_contributions[cid] = contribution
        recompute_category(cat)
        recompute_goal_funded(g)
        _evaluate_goal_status(g)
    return success(serializers.goal_contribution(contribution), status=201)


@bp.route("/households/<household_id>/goals/<goal_id>/abandon", methods=["POST"])
@require_roles("HouseholdOwner")
def abandon(household_id, goal_id):
    h = get_household(household_id)
    g = get_goal(goal_id)
    enforce_household_access(household_id)
    if g["household_id"] != household_id:
        raise errors.not_found("Goal not found in household")

    # State: abandon defined only from ACTIVE.
    if g["status"] != "ACTIVE":
        raise errors.invalid_state("Goal is not ACTIVE")

    with lock:
        for gc in db.goal_contributions.values():
            if gc["goal_id"] == goal_id and not gc["reversed"]:
                gc["reversed"] = True
        g["status"] = "ABANDONED"
        touch(g)
        recompute_goal_funded(g)
        cat = db.budget_categories.get(g["funding_category_id"])
        if cat is not None:
            recompute_category(cat)
        recompute_posture(h)
    return success(serializers.goal(g), status=200)


@bp.route("/households/goal-contributions/<c_id>", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def get_contribution_route(c_id):
    c = get_contribution(c_id)
    goal = db.goals.get(c["goal_id"])
    if goal is not None:
        enforce_household_access(goal["household_id"])
    return success(serializers.goal_contribution(c), status=200)


@bp.route("/households/goal-contributions", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def list_contributions():
    goal_id = request.args.get("goal_id")
    items = list(db.goal_contributions.values())
    if goal_id is not None:
        items = [c for c in items if c["goal_id"] == goal_id]
    return paginate_and_respond(items, serializers.goal_contribution)
