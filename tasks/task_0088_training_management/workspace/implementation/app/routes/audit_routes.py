"""AuditLog endpoint."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..pagination import parse_limit_offset
from ..store import get_store
from ..services.serializers import serialize_audit_log
from ._helpers import ok_list, sort_by_created, with_lock


def register(app: Flask) -> None:
    @app.get("/training/audit-logs")
    @require_auth("TrainingAdmin")
    @with_lock
    def list_audit_logs():
        limit, offset = parse_limit_offset()
        subject_kind = request.args.get("subject_kind")
        subject_id = request.args.get("subject_id")
        action = request.args.get("action")
        items = list(get_store().audit_logs.values())
        if subject_kind:
            items = [a for a in items if a["subject_kind"] == subject_kind]
        if subject_id:
            items = [a for a in items if a["subject_id"] == subject_id]
        if action:
            items = [a for a in items if a["action"] == action]
        items = sort_by_created(items)
        return ok_list([serialize_audit_log(a) for a in items], limit, offset)
