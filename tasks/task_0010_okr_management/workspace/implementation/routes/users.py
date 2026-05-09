"""User endpoints."""

from flask import Blueprint

import db
from auth import require_role
from envelope import success_object, success_array
from errors import ApiError
from serialize import s_user
from util import (get_json_body, parse_pagination, paginate,
                  require_fields, stamp_create)
from flask import request


bp = Blueprint("users", __name__)


@bp.post("/users")
def create_user():
    require_role("PlatformAdmin", "HRBP")
    body = get_json_body()
    require_fields(body, "email", "full_name", "department_id", "role_type")
    email = body["email"]
    full_name = body["full_name"]
    dept_id = body["department_id"]
    manager_id = body.get("manager_id")
    role_type = body["role_type"]
    if role_type not in ("EMPLOYEE", "MANAGER"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "role_type must be EMPLOYEE or MANAGER")
    if dept_id not in db.departments:
        raise ApiError("ERR_DEPARTMENT_NOT_FOUND", 404, "department not found")
    if manager_id is not None and manager_id not in db.users:
        raise ApiError("ERR_USER_NOT_FOUND", 404, "manager not found")
    # Email uniqueness
    for u in db.users.values():
        if u["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"email '{email}' already exists")
    user = {
        "email": email,
        "full_name": full_name,
        "department_id": dept_id,
        "manager_id": manager_id,
        "role_type": role_type,
        "status": "ACTIVE",
    }
    stamp_create(user)
    db.users[user["id"]] = user
    return success_object(s_user(user), status=201)


@bp.get("/users")
def list_users():
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    limit, offset = parse_pagination()
    dept_id = request.args.get("department_id")
    role_type = request.args.get("role_type")
    items = list(db.users.values())
    if dept_id is not None:
        items = [u for u in items if u["department_id"] == dept_id]
    if role_type is not None:
        items = [u for u in items if u["role_type"] == role_type]
    items.sort(key=lambda u: u["created_at"])
    page, total = paginate(items, limit, offset)
    return success_array([s_user(u) for u in page], total, limit, offset)


@bp.get("/users/<id>")
def read_user(id):
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    u = db.users.get(id)
    if not u:
        raise ApiError("ERR_USER_NOT_FOUND", 404, "user not found")
    return success_object(s_user(u))
