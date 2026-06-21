"""Instructors (PRD §3.3)."""
from flask import Blueprint

from db import db
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_DUPLICATE
from middleware import (
    get_identity, require_roles, ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER,
)
from response import success
from common import (
    get_json_body, require_fields, require_email, require_enum,
    parse_pagination, paginate, sort_by_created,
)
from services.serialize import view, view_list

bp = Blueprint("instructors", __name__)
ALL_ROLES = [ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER]
RANK_LEVELS = {"INSTRUCTOR", "CHIEF_INSTRUCTOR"}


@bp.post("/dojo/instructors")
def create_instructor():
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    body = get_json_body()
    require_fields(body, ["full_name", "email"])
    if not isinstance(body["full_name"], str) or not (1 <= len(body["full_name"]) <= 120):
        raise err(ERR_INVALID_REQUEST, "full_name must be 1..120 chars.")
    require_email(body["email"], "email")
    rank_level = body.get("rank_level", "INSTRUCTOR")
    require_enum(rank_level, RANK_LEVELS, "rank_level")

    for i in db.instructors.values():
        if i["email"] == body["email"]:
            raise err(ERR_DUPLICATE, "Instructor email already exists.")

    now = db.now_iso()
    iid = db.new_id()
    instructor = {
        "id": iid,
        "full_name": body["full_name"],
        "email": body["email"],
        "rank_level": rank_level,
        "is_available": True,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.instructors[iid] = instructor
    return success(view(instructor), 201)


@bp.get("/dojo/instructors/<iid>")
def get_instructor(iid):
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    instructor = db.instructors.get(iid)
    if instructor is None:
        raise err(ERR_NOT_FOUND, "Instructor not found.")
    return success(view(instructor), 200)


@bp.get("/dojo/instructors")
def list_instructors():
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.instructors.values()))
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)
