"""Meal plan routes: get, list, change tier."""

from flask import Blueprint, request

import db
import errors
import response
import common
from middleware import authenticate, require_role
from services import core

bp = Blueprint("meal_plans", __name__)

ALL_ROLES = ("HousingOfficer", "Student", "ResidentAdvisor")
TIERS = {"NONE", "COMMUTER", "STANDARD", "UNLIMITED"}


@bp.route("/meal-plans/<meal_plan_id>", methods=["GET"])
def get_meal_plan(meal_plan_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        rec = core.get_or_404(db.meal_plans, meal_plan_id)
        return response.object_response(core.serialize(rec))


@bp.route("/meal-plans", methods=["GET"])
def list_meal_plans():
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        limit, offset = common.parse_pagination()
        items = list(db.meal_plans.values())
        val = request.args.get("assignment_id")
        if val is not None:
            items = [m for m in items if m["assignment_id"] == val]
        items = common.sort_by_created(items)
        page, total = common.paginate(items, limit, offset)
        return response.array_response(
            [core.serialize(m) for m in page], limit, offset, total
        )


@bp.route("/meal-plans/<meal_plan_id>", methods=["PATCH"])
def change_tier(meal_plan_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        mp = core.get_or_404(db.meal_plans, meal_plan_id)
        # Ownership: the meal plan's assignment's student.
        assignment = db.assignments.get(mp["assignment_id"])
        if assignment is None or principal.user_id != assignment["student_id"]:
            raise errors.forbidden("Caller does not own this meal plan.")
        body = common.get_body()
        common.require_fields(body, ["tier"])
        tier = common.require_enum(body, "tier", TIERS)
        if mp["status"] != "ACTIVE":
            raise errors.invalid_state("Meal plan is not ACTIVE.")
        mp["tier"] = tier
        mp["weekly_fee_cents"] = core.TIER_FEE[tier]
        core.touch(mp)
        return response.object_response(core.serialize(mp))
