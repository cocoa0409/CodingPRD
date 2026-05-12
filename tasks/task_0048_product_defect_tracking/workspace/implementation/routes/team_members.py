"""TeamMember endpoints."""

from __future__ import annotations

from flask import Blueprint, request

import db
from config import ROLE_TRIAGE_MANAGER, ROLE_ANY, TM_ROLES, TM_STATUS_ACTIVE
from errors import AppError
from middleware import require_role
from response import parse_pagination, success, success_list
from services.serializers import team_member_dto
from services.validators import (
    find_project_or_404, find_team_member_or_404, ensure_project_active,
    get_json, require_enum, require_str,
)

bp = Blueprint("team_members", __name__)


@bp.post("/projects/<project_id>/team-members")
def create_team_member(project_id):
    require_role(ROLE_TRIAGE_MANAGER)
    body = get_json()
    project = find_project_or_404(project_id)
    ensure_project_active(project)
    display_name = require_str(body, "display_name")
    role = require_enum(body, "role", TM_ROLES)
    tm = db.insert("team_members", {
        "project_id": project_id,
        "display_name": display_name,
        "role": role,
        "active_workload": 0,
        "status": TM_STATUS_ACTIVE,
    })
    return success(team_member_dto(tm), 201)


@bp.get("/projects/<project_id>/team-members")
def list_team_members(project_id):
    require_role(ROLE_ANY)
    find_project_or_404(project_id)
    limit, offset = parse_pagination(request.args)
    role_filter = request.args.get("role")
    filters = {"project_id": project_id}
    if role_filter:
        filters["role"] = role_filter
    rows, total = db.query("team_members", filters=filters, limit=limit, offset=offset)
    return success_list([team_member_dto(r) for r in rows], total, limit, offset)


@bp.get("/projects/<project_id>/team-members/<tm_id>")
def get_team_member(project_id, tm_id):
    require_role(ROLE_ANY)
    find_project_or_404(project_id)
    tm = find_team_member_or_404(tm_id)
    if tm["project_id"] != project_id:
        raise AppError("ERR_TEAM_MEMBER_NOT_FOUND", "TeamMember not in this project", 404)
    return success(team_member_dto(tm))
