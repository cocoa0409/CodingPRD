"""Department endpoints."""

from flask import Blueprint

import db
from auth import require_role
from audit import write_audit
from envelope import success_object, success_array
from errors import ApiError
from serialize import s_department
from util import (gen_id, get_json_body, parse_pagination, paginate,
                  require_fields, stamp_create)


bp = Blueprint("departments", __name__)


@bp.post("/departments")
def create_department():
    require_role("PlatformAdmin")
    body = get_json_body()
    require_fields(body, "code", "name")
    code = body["code"]
    name = body["name"]
    parent_id = body.get("parent_department_id")
    if not isinstance(code, str) or not isinstance(name, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "code/name must be strings")
    # Existence check on parent department
    if parent_id is not None:
        if parent_id not in db.departments:
            raise ApiError("ERR_DEPARTMENT_NOT_FOUND", 404, "parent department not found")
    # Uniqueness on code
    for d in db.departments.values():
        if d["code"] == code:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"department code '{code}' already exists")
    dept = {
        "code": code,
        "name": name,
        "parent_department_id": parent_id,
    }
    stamp_create(dept)
    db.departments[dept["id"]] = dept
    return success_object(s_department(dept), status=201)


@bp.get("/departments")
def list_departments():
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    limit, offset = parse_pagination()
    items = sorted(db.departments.values(), key=lambda d: d["created_at"])
    page, total = paginate(items, limit, offset)
    return success_array([s_department(d) for d in page], total, limit, offset)
