"""Audit log listing endpoint."""

from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_role
from response import success_list, parse_pagination
from config import ROLE_ADMIN
from services.serializers import serialize


bp = Blueprint("audit", __name__, url_prefix="/consultation/audit-logs")


@bp.get("")
def list_audit():
    require_role(ROLE_ADMIN)
    limit, offset = parse_pagination(request.args)
    filters = {}
    for k in ("target_entity", "action_code", "actor_role"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    rows = db.all_rows("audit_logs")
    if filters:
        rows = [r for r in rows if all(r.get(k) == v for k, v in filters.items())]
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize(r) for r in page], total, limit, offset)
