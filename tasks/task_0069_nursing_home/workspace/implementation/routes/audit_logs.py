"""Audit logs read endpoint."""
from flask import request

from db import get_db
from helpers import paginate, parse_pagination
from middleware import require_roles
from response import list_success


def register(app):

    @app.get("/audit-logs")
    @require_roles("Admin", "Supervisor")
    def list_audit_logs(user_id, role):
        limit, offset = parse_pagination()
        entity_type = request.args.get("entity_type")
        entity_id = request.args.get("entity_id")
        db = get_db()
        items = list(db.audit_logs.values())
        if entity_type:
            items = [a for a in items if a["entity_type"] == entity_type]
        if entity_id:
            items = [a for a in items if a["entity_id"] == entity_id]
        items.sort(key=lambda a: a["occurred_at"])
        page, total = paginate(items, limit, offset)
        return list_success([dict(a) for a in page], limit, offset, total)
