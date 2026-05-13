"""Audit log routes (Regulator only)."""

from flask import Blueprint, request

from common import get_pagination, slice_page
from db import db
from middleware import require_roles
from response import paginated


bp = Blueprint("audit_logs", __name__, url_prefix="/procurement")


@bp.get("/audit-logs")
@require_roles("Regulator")
def list_logs():
    limit, offset = get_pagination()
    items = list(db.audit_logs)
    tt = request.args.get("target_type")
    tid = request.args.get("target_id")
    action = request.args.get("action")
    if tt:
        items = [x for x in items if x.get("target_type") == tt]
    if tid:
        items = [x for x in items if x.get("target_id") == tid]
    if action:
        items = [x for x in items if x.get("action") == action]
    items.sort(key=lambda x: x["created_at"])
    page, total = slice_page(items, limit, offset)
    return paginated(page, limit, offset, total, 200)
