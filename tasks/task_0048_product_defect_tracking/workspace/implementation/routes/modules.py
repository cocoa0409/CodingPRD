"""Module endpoints."""

from __future__ import annotations

from flask import Blueprint, g, request

import db
from config import ACTIVE, ARCHIVED, ROLE_TRIAGE_MANAGER, ROLE_ANY
from errors import AppError, ERR_INVALID_MODULE_KLOC, ERR_INVALID_REQUEST, ERR_MODULE_HAS_ACTIVE_DEFECTS
from middleware import require_role
from response import parse_pagination, success, success_list
from services.audit import append_audit
from services.serializers import module_dto
from services.validators import (
    check_version, find_module_or_404, find_project_or_404, ensure_project_active,
    get_json, require_int, require_number, require_str,
)

bp = Blueprint("modules", __name__)


def _validate_module_in_project(project_id, module_id):
    project = find_project_or_404(project_id)
    module = find_module_or_404(module_id)
    if module["project_id"] != project_id:
        # treat as not found
        raise AppError("ERR_MODULE_NOT_FOUND", "Module not in this project", 404)
    return project, module


@bp.post("/projects/<project_id>/modules")
def create_module(project_id):
    require_role(ROLE_TRIAGE_MANAGER)
    body = get_json()
    project = find_project_or_404(project_id)
    ensure_project_active(project)

    module_key = require_str(body, "module_key")
    owner_team_member_id = require_str(body, "owner_team_member_id")
    kloc = require_number(body, "kloc")
    initial_defect_quota = require_int(body, "initial_defect_quota")

    if kloc <= 0:
        raise AppError(ERR_INVALID_MODULE_KLOC, "kloc must be > 0", 400)
    if initial_defect_quota < 1:
        raise AppError(ERR_INVALID_REQUEST, "initial_defect_quota must be >= 1", 400)

    module = db.insert("modules", {
        "project_id": project_id,
        "module_key": module_key,
        "owner_team_member_id": owner_team_member_id,
        "kloc": kloc,
        "initial_defect_quota": initial_defect_quota,
        "active_defect_count": 0,
        "quota_remaining": initial_defect_quota,
        "status": ACTIVE,
    })
    return success(module_dto(module), 201)


@bp.get("/projects/<project_id>/modules")
def list_modules(project_id):
    require_role(ROLE_ANY)
    find_project_or_404(project_id)
    limit, offset = parse_pagination(request.args)
    rows, total = db.query("modules", filters={"project_id": project_id},
                           limit=limit, offset=offset)
    return success_list([module_dto(r) for r in rows], total, limit, offset)


@bp.get("/projects/<project_id>/modules/<module_id>")
def get_module(project_id, module_id):
    require_role(ROLE_ANY)
    _, module = _validate_module_in_project(project_id, module_id)
    return success(module_dto(module))


@bp.post("/projects/<project_id>/modules/<module_id>/archive")
def archive_module(project_id, module_id):
    require_role(ROLE_TRIAGE_MANAGER)
    body = get_json()
    project, module = _validate_module_in_project(project_id, module_id)
    ensure_project_active(project)
    check_version(body, module)
    if module["status"] == ARCHIVED:
        return success(module_dto(module))
    if module.get("active_defect_count", 0) > 0:
        raise AppError(
            ERR_MODULE_HAS_ACTIVE_DEFECTS,
            "Cannot archive module with active defects.",
            409,
        )
    db.update("modules", module_id, {"status": ARCHIVED}, bump=True)
    append_audit(
        defect_id=None,
        event_type="STATUS_CHANGE",
        actor_id=g.user_id,
        from_value=ACTIVE,
        to_value=ARCHIVED,
        at_minute=project["clock_minute"],
    )
    updated = db.find_by_id("modules", module_id)
    return success(module_dto(updated))
