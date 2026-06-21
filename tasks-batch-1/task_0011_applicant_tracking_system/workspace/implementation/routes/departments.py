"""Department endpoints."""
from flask import Blueprint

import db
from auth import require_role
from common import (
    get_json_or_400,
    require_str,
    require_int,
    new_id,
    now_iso,
    parse_pagination,
    paginate,
    get_or_404,
)
from errors import ApiError, ERR_INVALID_REQUEST
from response import success_object, success_array
from serializers import ser_department


bp = Blueprint("departments", __name__)


@bp.post("/ats/departments")
def create_department():
    require_role({"PlatformAdmin"})
    body = get_json_or_400()
    name = require_str(body, "name")
    cost_center_code = require_str(body, "cost_center_code")
    hiring_budget_cents = require_int(body, "hiring_budget_cents", minimum=0)

    # Unique cost_center_code.
    for existing in db.departments.values():
        if existing["cost_center_code"] == cost_center_code:
            raise ApiError(ERR_INVALID_REQUEST, 400, "cost_center_code already in use")

    dept = {
        "id": new_id(),
        "name": name,
        "cost_center_code": cost_center_code,
        "hiring_budget_cents": hiring_budget_cents,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.departments[dept["id"]] = dept
    return success_object(ser_department(dept), status=201)


@bp.get("/ats/departments/<dept_id>")
def read_department(dept_id):
    require_role({"PlatformAdmin", "HiringManager", "Recruiter"})
    dept = get_or_404(db.departments, dept_id, "department")
    return success_object(ser_department(dept), status=200)


@bp.get("/ats/departments")
def list_departments():
    require_role({"PlatformAdmin", "HiringManager", "Recruiter"})
    limit, offset = parse_pagination()
    rows = sorted(db.departments.values(), key=lambda d: d["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([ser_department(d) for d in page], limit, offset, total, status=200)
