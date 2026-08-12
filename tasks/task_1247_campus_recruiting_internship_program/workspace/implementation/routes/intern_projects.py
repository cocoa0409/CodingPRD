"""InternProject routes."""

from flask import Blueprint, request

from db import db
from middleware import require_auth
from response import success_object, success_list
from services.domain import (
    get_season,
    get_intern_project,
    intern_project_view,
    project_assignment_view,
)
from utils import (
    parse_pagination,
    require_int,
    require_string,
    stamp_new,
    touch,
)

bp = Blueprint("intern_projects", __name__)


@bp.route("/seasons/<sid>/intern-projects", methods=["POST"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def create_intern_project(sid):
    get_season(sid)
    payload = request.get_json(silent=True) or {}
    title = require_string(payload, "title")
    capacity = require_int(payload, "capacity", min_value=1)
    p = {
        "season_id": sid,
        "title": title,
        "capacity": capacity,
        "assigned_count": 0,
        "status": "OPEN",
    }
    stamp_new(p)
    db.intern_projects[p["id"]] = p
    return success_object(intern_project_view(p), 201)


@bp.route("/seasons/<sid>/intern-projects", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def list_intern_projects(sid):
    get_season(sid)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [
        p for p in db.intern_projects.values()
        if p["season_id"] == sid and (status is None or p["status"] == status)
    ]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([intern_project_view(p) for p in page], total, limit, offset)


@bp.route("/intern-projects/<pid>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def get_one_intern_project(pid):
    p = get_intern_project(pid)
    return success_object(intern_project_view(p))


@bp.route("/intern-projects/<pid>/close", methods=["POST"])
@require_auth(["Recruiter"])
def close_intern_project(pid):
    from errors import err_project_state_forbidden
    p = get_intern_project(pid)
    if p["status"] != "OPEN":
        raise err_project_state_forbidden("close requires OPEN")
    p["status"] = "CLOSED"
    touch(p)
    return success_object(intern_project_view(p))


@bp.route("/intern-projects/<pid>/project-assignments", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def list_project_assignments(pid):
    get_intern_project(pid)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [
        a for a in db.project_assignments.values()
        if a["intern_project_id"] == pid
        and (status is None or a["status"] == status)
    ]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([project_assignment_view(a) for a in page], total, limit, offset)
