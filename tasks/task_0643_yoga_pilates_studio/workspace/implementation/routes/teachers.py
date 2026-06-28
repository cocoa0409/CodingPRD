"""Teacher endpoints + teacher-scoped relationship reads."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import authenticate, require_roles
from models import make_teacher, serialize
from response import success, list_success
from helpers import (get_json_body, parse_pagination, paginate,
                     require_str, find_or_404)

bp = Blueprint("teachers", __name__)

CATALOG_READERS = {"StudioManager", "Member", "Instructor"}


@bp.post("/teachers")
def create_teacher():
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    body = get_json_body()
    full_name = require_str(body, "full_name")
    certifications = body.get("certifications")
    if not isinstance(certifications, list) or not all(isinstance(c, str) for c in certifications):
        raise err("ERR_INVALID_REQUEST", "certifications must be an array of strings")
    teacher = make_teacher(full_name, certifications)
    store.teachers[teacher["id"]] = teacher
    return success(serialize(teacher), status=201)


@bp.get("/teachers/<tid>")
def get_teacher(tid):
    principal = authenticate()
    require_roles(principal, CATALOG_READERS)
    teacher = find_or_404(store.teachers, tid, "Teacher")
    return success(serialize(teacher))


@bp.get("/teachers/<tid>/class-sessions")
def teacher_sessions(tid):
    principal = authenticate()
    require_roles(principal, CATALOG_READERS)
    find_or_404(store.teachers, tid, "Teacher")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [s for s in store.class_sessions.values() if s["teacher_id"] == tid]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_success([serialize(s) for s in window], 200, limit, offset, total)


@bp.get("/teachers/<tid>/workshops")
def teacher_workshops(tid):
    principal = authenticate()
    require_roles(principal, CATALOG_READERS)
    find_or_404(store.teachers, tid, "Teacher")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [w for w in store.workshops.values() if w["lead_teacher_id"] == tid]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_success([serialize(w) for w in window], 200, limit, offset, total)
