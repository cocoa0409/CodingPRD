"""Defect attachment endpoints."""

from __future__ import annotations

from flask import Blueprint, g, request

import db
from config import (
    ATTACH_TYPES, ATTACH_SIZE_CAPS,
    ROLE_DEVELOPER, ROLE_QA_ENGINEER, ROLE_TRIAGE_MANAGER, ROLE_ANY,
)
from errors import AppError, ERR_ATTACHMENT_TOO_LARGE, ERR_INVALID_REQUEST
from middleware import require_role
from response import parse_pagination, success, success_list
from services.serializers import attachment_dto
from services.validators import (
    find_defect_or_404, find_project_or_404, ensure_project_active,
    get_json, require_enum, require_int, require_str,
)

bp = Blueprint("attachments", __name__)


@bp.post("/defects/<defect_id>/attachments")
def upload_attachment(defect_id):
    require_role(ROLE_DEVELOPER, ROLE_QA_ENGINEER, ROLE_TRIAGE_MANAGER)
    body = get_json()
    d = find_defect_or_404(defect_id)
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    attachment_type = require_enum(body, "attachment_type", ATTACH_TYPES)
    filename = require_str(body, "filename")
    size_bytes = require_int(body, "size_bytes")
    if size_bytes <= 0:
        raise AppError(ERR_INVALID_REQUEST, "size_bytes must be > 0", 400)
    cap = ATTACH_SIZE_CAPS[attachment_type]
    if size_bytes > cap:
        raise AppError(ERR_ATTACHMENT_TOO_LARGE,
                       f"size_bytes exceeds {attachment_type} cap of {cap}", 400)

    row = db.insert("defect_attachments", {
        "defect_id": defect_id,
        "attachment_type": attachment_type,
        "filename": filename,
        "size_bytes": size_bytes,
        "uploaded_by": g.user_id,
    })
    return success(attachment_dto(row), 201)


@bp.get("/defects/<defect_id>/attachments")
def list_attachments(defect_id):
    require_role(ROLE_ANY)
    find_defect_or_404(defect_id)
    limit, offset = parse_pagination(request.args)
    rows, total = db.query("defect_attachments", filters={"defect_id": defect_id},
                           limit=limit, offset=offset)
    return success_list([attachment_dto(r) for r in rows], total, limit, offset)
