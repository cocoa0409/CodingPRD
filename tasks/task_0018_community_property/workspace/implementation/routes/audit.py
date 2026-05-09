"""GET /audit-entries — list audit entries with optional filters."""
from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_roles
from response import success_list
from utils import paginate, parse_pagination

bp = Blueprint("audit", __name__)


@bp.get("/audit-entries")
@require_roles("PropertyManager", "CommitteeChair")
def list_audit():
    subject_kind = request.args.get("subject_kind")
    subject_id = request.args.get("subject_id")
    items = list(db.audit_entries.values())
    if subject_kind:
        items = [e for e in items if e.get("subject_kind") == subject_kind]
    if subject_id:
        items = [e for e in items if e.get("subject_id") == subject_id]
    items.sort(key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)
