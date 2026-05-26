"""DiversityGoal endpoints."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (
    get_json_or_400,
    require_str,
    require_int,
    require_number,
    require_enum,
    new_id,
    now_iso,
    parse_pagination,
    paginate,
    get_or_404,
    fk_or_404,
)
from errors import ApiError, ERR_INVALID_REQUEST
from response import success_object, success_array
from serializers import ser_diversity_goal


bp = Blueprint("diversity_goals", __name__)


TARGET_LEVELS = {"JUNIOR", "MID", "SENIOR", "STAFF"}


@bp.post("/ats/diversity-goals")
def create_diversity_goal():
    require_role({"PlatformAdmin"})
    body = get_json_or_400()
    department_id = require_str(body, "department_id")
    target_level = require_enum(body, "target_level", TARGET_LEVELS)
    period_year = require_int(body, "period_year", minimum=2000)
    target_pct = require_number(body, "target_underrepresented_pct", minimum=0.0, maximum=1.0)

    fk_or_404(db.departments, department_id, "department")

    # Unique (department_id, target_level, period_year).
    for g in db.diversity_goals.values():
        if (g["department_id"], g["target_level"], g["period_year"]) == (department_id, target_level, period_year):
            raise ApiError(ERR_INVALID_REQUEST, 400, "diversity goal already exists for (department, level, year)")

    goal = {
        "id": new_id(),
        "department_id": department_id,
        "target_level": target_level,
        "period_year": period_year,
        "target_underrepresented_pct": target_pct,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.diversity_goals[goal["id"]] = goal
    return success_object(ser_diversity_goal(goal), status=201)


@bp.get("/ats/diversity-goals/<goal_id>")
def read_diversity_goal(goal_id):
    require_role({"PlatformAdmin", "HiringManager"})
    goal = get_or_404(db.diversity_goals, goal_id, "diversity goal")
    return success_object(ser_diversity_goal(goal), status=200)


@bp.get("/ats/diversity-goals")
def list_diversity_goals():
    require_role({"PlatformAdmin", "HiringManager"})
    limit, offset = parse_pagination()
    rows = list(db.diversity_goals.values())
    dept_f = request.args.get("department_id")
    year_f = request.args.get("period_year")
    level_f = request.args.get("target_level")
    if dept_f:
        rows = [g for g in rows if g["department_id"] == dept_f]
    if year_f:
        try:
            year_int = int(year_f)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "period_year filter must be integer")
        rows = [g for g in rows if g["period_year"] == year_int]
    if level_f:
        rows = [g for g in rows if g["target_level"] == level_f]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([ser_diversity_goal(g) for g in page], limit, offset, total, status=200)
