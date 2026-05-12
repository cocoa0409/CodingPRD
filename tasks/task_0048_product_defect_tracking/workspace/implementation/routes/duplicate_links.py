"""DuplicateLink endpoints."""

from __future__ import annotations

from flask import Blueprint, g, request

import db
from config import DEFECT_NEW, DEFECT_CLOSED, ROLE_TRIAGE_MANAGER, ROLE_ANY
from errors import (
    AppError, ERR_DEFECT_ALREADY_LINKED, ERR_INVALID_DUPLICATE_LINK,
    ERR_INVALID_REQUEST,
)
from middleware import require_role
from response import parse_pagination, success, success_list
from services.serializers import duplicate_link_dto
from services.validators import (
    find_defect_or_404, find_project_or_404, ensure_project_active,
    get_json, require_number, require_str,
)

bp = Blueprint("duplicate_links", __name__)


@bp.post("/duplicate-links")
def create_duplicate_link():
    require_role(ROLE_TRIAGE_MANAGER)
    body = get_json()
    duplicate_defect_id = require_str(body, "duplicate_defect_id")
    canonical_defect_id = require_str(body, "canonical_defect_id")
    similarity_score = require_number(body, "similarity_score")

    dup = find_defect_or_404(duplicate_defect_id)
    canon = find_defect_or_404(canonical_defect_id)
    project = find_project_or_404(dup["project_id"])
    ensure_project_active(project)

    # Invariants under ERR_INVALID_DUPLICATE_LINK umbrella
    if duplicate_defect_id == canonical_defect_id:
        raise AppError(ERR_INVALID_DUPLICATE_LINK, "Cannot link defect to itself.", 400)
    if canon.get("canonical_defect_id"):
        raise AppError(ERR_INVALID_DUPLICATE_LINK,
                       "Canonical defect is itself a duplicate.", 400)
    if dup["status"] != DEFECT_NEW:
        raise AppError(ERR_INVALID_DUPLICATE_LINK,
                       "Duplicate defect must be in status NEW.", 400)
    if canon["status"] == DEFECT_CLOSED:
        raise AppError(ERR_INVALID_DUPLICATE_LINK,
                       "Canonical defect must be non-terminal.", 400)
    if similarity_score < 0.0 or similarity_score > 1.0:
        raise AppError(ERR_INVALID_DUPLICATE_LINK,
                       "similarity_score must be between 0.0 and 1.0.", 400)
    if similarity_score < 0.5:
        raise AppError(ERR_INVALID_DUPLICATE_LINK,
                       "similarity_score must be at least 0.5.", 400)

    # Already-linked check (the duplicate defect must not already have canonical set)
    if dup.get("canonical_defect_id"):
        raise AppError(ERR_DEFECT_ALREADY_LINKED,
                       "Duplicate defect already linked.", 409)

    link = db.insert("duplicate_links", {
        "duplicate_defect_id": duplicate_defect_id,
        "canonical_defect_id": canonical_defect_id,
        "linked_by": g.user_id,
        "similarity_score": similarity_score,
    })
    db.update("defects", duplicate_defect_id,
              {"canonical_defect_id": canonical_defect_id}, bump=True)
    return success(duplicate_link_dto(link), 201)


@bp.get("/duplicate-links")
def list_duplicate_links():
    require_role(ROLE_ANY)
    limit, offset = parse_pagination(request.args)
    filters = {}
    for k in ("duplicate_defect_id", "canonical_defect_id"):
        v = request.args.get(k)
        if v:
            filters[k] = v
    rows, total = db.query("duplicate_links", filters=filters,
                           limit=limit, offset=offset)
    return success_list([duplicate_link_dto(r) for r in rows], total, limit, offset)
