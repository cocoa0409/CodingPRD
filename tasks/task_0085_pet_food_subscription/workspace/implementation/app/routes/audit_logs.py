"""Audit log read endpoint (AdminOps only)."""
from __future__ import annotations

from flask import Blueprint, request

from app.auth import require_role
from app.pagination import paginate, parse_pagination
from app.response import success_array
from app.store import store


bp = Blueprint("audit_logs", __name__)


@bp.route("/audit-logs", methods=["GET"])
@require_role("AdminOps")
def list_audit_logs(user_id: str, role: str):
    limit, offset = parse_pagination()
    etype = request.args.get("entity_type")
    eid = request.args.get("entity_id")
    evtype = request.args.get("event_type")
    items = list(store.audit_logs)
    if etype:
        items = [a for a in items if a.get("entity_type") == etype]
    if eid:
        items = [a for a in items if a.get("entity_id") == eid]
    if evtype:
        items = [a for a in items if a.get("event_type") == evtype]
    items.sort(key=lambda a: (a.get("created_at", ""), a.get("id", "")))
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total)
