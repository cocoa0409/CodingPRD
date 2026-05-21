"""DiversityGoal routes — create, read, lock."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..clock import iso_format, now
from ..common import bump, get_json_body, positive_int, require_fields, require_str, stamp_new
from ..errors import ApiError
from ..lookups import path_diversity_goal
from ..response import respond
from ..serializers import serialize_diversity_goal
from ..services import recompute_diversity_goal
from ..store import store


diversity_goals_bp = Blueprint("diversity_goals", __name__)


@diversity_goals_bp.post("/diversity-goals")
@require_auth("PlatformAdmin")
def create_diversity_goal():
    body = get_json_body()
    require_fields(body, "department_code", "period_year", "target_protected_class_percentage")
    department_code = require_str(body["department_code"], "department_code")
    period_year = positive_int(body["period_year"], "period_year")
    if period_year < 2020:
        raise ApiError("ERR_VALIDATION", "period_year must be >= 2020")
    target = body["target_protected_class_percentage"]
    if isinstance(target, bool) or not isinstance(target, (int, float)):
        raise ApiError("ERR_VALIDATION", "target_protected_class_percentage must be numeric")
    if target <= 0 or target > 100:
        raise ApiError("ERR_VALIDATION", "target_protected_class_percentage must be in (0, 100]")

    with store.lock:
        # Uniqueness on (department_code, period_year).
        for g in store.diversity_goals.values():
            if g["department_code"] == department_code and g["period_year"] == period_year:
                raise ApiError(
                    "ERR_VALIDATION",
                    "DiversityGoal already exists for this department and year",
                )
        goal = stamp_new({
            "department_code": department_code,
            "period_year": period_year,
            "target_protected_class_percentage": float(target),
            "realized_percentage": 0.00,
            "projected_percentage": 0.00,
            "locked": False,
            "locked_at": None,
        })
        store.diversity_goals[goal["id"]] = goal
        recompute_diversity_goal(goal["id"])
    return respond(serialize_diversity_goal(goal), 201)


@diversity_goals_bp.get("/diversity-goals/<gid>")
@require_auth("PlatformAdmin", "Recruiter", "HiringManager")
def get_diversity_goal(gid):
    with store.lock:
        goal = path_diversity_goal(gid)
        # Always reflect the latest progress on read.
        recompute_diversity_goal(gid)
        return respond(serialize_diversity_goal(goal))


@diversity_goals_bp.post("/diversity-goals/<gid>/lock")
@require_auth("PlatformAdmin")
def lock_diversity_goal(gid):
    with store.lock:
        goal = path_diversity_goal(gid)
        recompute_diversity_goal(gid)
        if goal["realized_percentage"] < goal["target_protected_class_percentage"]:
            raise ApiError(
                "ERR_DIVERSITY_GOAL_NOT_MET",
                "realized_percentage is below target_protected_class_percentage",
            )
        goal["locked"] = True
        goal["locked_at"] = iso_format(now())
        bump(goal)
        return respond(serialize_diversity_goal(goal))
