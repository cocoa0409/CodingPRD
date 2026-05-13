"""Audit log endpoints."""

from flask import Blueprint, request

import db
from middleware import require_roles
from response import paginated
from validators import get_pagination, paginate_list


bp = Blueprint("audit", __name__)


@bp.get("/audit-logs")
@require_roles({"PlatformOperator", "CustomerService"})
def list_audit_logs():
    event_kind = request.args.get("event_kind")
    entity_kind = request.args.get("entity_kind")
    entity_id = request.args.get("entity_id")
    limit, offset = get_pagination()
    items = sorted(db.audit_logs.values(), key=lambda r: r["_seq"])
    if event_kind:
        items = [a for a in items if a["event_kind"] == event_kind]
    if entity_kind:
        items = [a for a in items if a["entity_kind"] == entity_kind]
    if entity_id:
        items = [a for a in items if a["entity_id"] == entity_id]
    page, total = paginate_list(items, limit, offset)
    return paginated(db.public_list(page), limit, offset, total)
