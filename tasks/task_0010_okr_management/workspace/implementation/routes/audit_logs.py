"""Audit log list endpoint."""

from flask import Blueprint, request

import db
from auth import require_role
from envelope import success_array
from serialize import s_audit
from util import parse_pagination, paginate


bp = Blueprint("audit_logs", __name__)


@bp.get("/audit-logs")
def list_audit_logs():
    require_role("PlatformAdmin", "HRBP")
    limit, offset = parse_pagination()
    items = list(db.audit_logs.values())
    et = request.args.get("entity_type")
    eid = request.args.get("entity_id")
    auid = request.args.get("actor_user_id")
    action = request.args.get("action")
    if et:
        items = [a for a in items if a["entity_type"] == et]
    if eid:
        items = [a for a in items if a["entity_id"] == eid]
    if auid:
        items = [a for a in items if a["actor_user_id"] == auid]
    if action:
        items = [a for a in items if a["action"] == action]
    items.sort(key=lambda a: a["created_at"])
    page, total = paginate(items, limit, offset)
    return success_array([s_audit(a) for a in page], total, limit, offset)
