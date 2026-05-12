"""Project endpoints."""

from __future__ import annotations

from flask import Blueprint, g, request

import db
from config import (
    ACTIVE, ARCHIVED, DEFECT_NON_TERMINAL, ROLE_TRIAGE_MANAGER, ROLE_ANY,
)
from errors import AppError, ERR_MODULE_HAS_ACTIVE_DEFECTS
from middleware import require_role
from response import parse_pagination, success, success_list
from services.audit import append_audit
from services.serializers import project_dto
from services.validators import (
    check_version, find_project_or_404, get_json, require_str,
)

bp = Blueprint("projects", __name__)


@bp.post("/projects")
def create_project():
    require_role(ROLE_TRIAGE_MANAGER)
    body = get_json()
    project_key = require_str(body, "project_key")
    name = require_str(body, "name")
    project = db.insert("projects", {
        "project_key": project_key,
        "name": name,
        "clock_minute": 0,
        "status": ACTIVE,
    })
    return success(project_dto(project), 201)


@bp.get("/projects")
def list_projects():
    require_role(ROLE_ANY)
    limit, offset = parse_pagination(request.args)
    rows, total = db.query("projects", limit=limit, offset=offset)
    return success_list([project_dto(r) for r in rows], total, limit, offset)


@bp.get("/projects/<project_id>")
def get_project(project_id):
    require_role(ROLE_ANY)
    p = find_project_or_404(project_id)
    return success(project_dto(p))


@bp.post("/projects/<project_id>/archive")
def archive_project(project_id):
    require_role(ROLE_TRIAGE_MANAGER)
    body = get_json()
    p = find_project_or_404(project_id)
    if p["status"] == ARCHIVED:
        # Idempotent? PRD says archive only when ACTIVE; treat as no-op success
        return success(project_dto(p))
    check_version(body, p)

    # Precondition: zero non-terminal defects in project
    non_terminal_defects = [d for d in db.all_rows("defects")
                            if d["project_id"] == project_id and d["status"] in DEFECT_NON_TERMINAL]
    if non_terminal_defects:
        raise AppError(
            "ERR_MODULE_HAS_ACTIVE_DEFECTS",
            "Cannot archive project with non-terminal defects.",
            409,
        )

    # Also check each module's active_defect_count; if any > 0, abort entire cascade
    modules = [m for m in db.all_rows("modules") if m["project_id"] == project_id]
    for m in modules:
        if m.get("status") == ACTIVE and m.get("active_defect_count", 0) > 0:
            raise AppError(
                ERR_MODULE_HAS_ACTIVE_DEFECTS,
                f"Module {m['id']} has active defects; cannot cascade-archive.",
                409,
            )

    # Cascade: archive all active modules
    for m in modules:
        if m.get("status") == ACTIVE:
            db.update("modules", m["id"], {"status": ARCHIVED}, bump=True)
            append_audit(
                defect_id=None,
                event_type="STATUS_CHANGE",
                actor_id=g.user_id,
                from_value=ACTIVE,
                to_value=ARCHIVED,
                at_minute=p["clock_minute"],
            )

    db.update("projects", project_id, {"status": ARCHIVED}, bump=True)
    append_audit(
        defect_id=None,
        event_type="STATUS_CHANGE",
        actor_id=g.user_id,
        from_value=ACTIVE,
        to_value=ARCHIVED,
        at_minute=p["clock_minute"],
    )
    updated = db.find_by_id("projects", project_id)
    return success(project_dto(updated))
