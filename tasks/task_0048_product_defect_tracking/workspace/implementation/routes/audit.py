"""Audit entry listing."""

from __future__ import annotations

from flask import Blueprint, request

import db
from config import AUDIT_TYPES, ROLE_ANY
from errors import AppError, ERR_INVALID_REQUEST
from middleware import require_role
from response import parse_pagination, success_list
from services.serializers import audit_entry_dto

bp = Blueprint("audit", __name__)


def _parse_int(name, raw):
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise AppError(ERR_INVALID_REQUEST, f"{name} must be integer", 400)


@bp.get("/audit-entries")
def list_audit_entries():
    require_role(ROLE_ANY)
    limit, offset = parse_pagination(request.args)
    defect_id = request.args.get("defect_id")
    event_type = request.args.get("event_type")
    from_minute = _parse_int("from_minute", request.args.get("from_minute"))
    to_minute = _parse_int("to_minute", request.args.get("to_minute"))

    def matches(row):
        if defect_id is not None and row.get("defect_id") != defect_id:
            return False
        if event_type is not None and row.get("event_type") != event_type:
            return False
        if from_minute is not None and row.get("at_minute", 0) < from_minute:
            return False
        if to_minute is not None and row.get("at_minute", 0) > to_minute:
            return False
        return True

    rows, total = db.query("audit_entries", predicate=matches,
                           limit=limit, offset=offset)
    return success_list([audit_entry_dto(r) for r in rows], total, limit, offset)
